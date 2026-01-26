"""
LaTeX Source Validator

Validates LaTeX source code before compilation to catch common errors early.
Returns structured validation results with error positions and diagnostics.
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple
from enum import Enum


class ValidationErrorType(Enum):
    """Types of validation errors."""
    BRACKET_MISMATCH = "BRACKET_MISMATCH"
    ENVIRONMENT_MISMATCH = "ENVIRONMENT_MISMATCH"
    LIST_STRUCTURE_ERROR = "LIST_STRUCTURE_ERROR"
    MISSING_DOCUMENT_STRUCTURE = "MISSING_DOCUMENT_STRUCTURE"
    FORBIDDEN_COMMAND = "FORBIDDEN_COMMAND"
    UNDEFINED_COMMAND = "UNDEFINED_COMMAND"
    MISSING_PACKAGE = "MISSING_PACKAGE"


@dataclass
class ValidationError:
    """A single validation error."""
    error_type: ValidationErrorType
    message: str
    line_number: Optional[int] = None
    char_offset: Optional[int] = None
    context: Optional[str] = None  # Snippet around the error


@dataclass
class ValidationResult:
    """Result of LaTeX validation."""
    is_valid: bool
    errors: List[ValidationError]
    
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.errors) > 0


class LaTeXValidator:
    """
    Validates LaTeX source code for common errors.
    
    Checks:
    1. Bracket balance ({})
    2. Environment balance (\begin{...} / \end{...})
    3. List structure (items inside lists)
    4. Document structure (\documentclass, \begin{document}, \end{document})
    5. Forbidden commands (security)
    6. Undefined control sequences (heuristic)
    """
    
    # Forbidden commands for security
    FORBIDDEN_PATTERNS = [
        (r'\\write18', 'Shell escape via \\write18'),
        (r'\\immediate\\write18', 'Shell escape via \\immediate\\write18'),
        (r'\\input\{[|]', 'Input from pipe'),
        (r'\\openin', 'File input command'),
        (r'\\openout', 'File output command'),
        (r'\\read\s', 'Read command'),
        (r'\\write(?!18)', 'Write command (excluding write18)'),
        (r'\\catcode', 'Category code manipulation'),
        (r'\\special\{.*shell', 'Shell escape via \\special'),
    ]
    
    # Common LaTeX commands that are always valid
    # This is a whitelist of standard LaTeX commands that don't require packages
    STANDARD_COMMANDS = {
        # Document structure
        'documentclass', 'begin', 'end', 'document',
        # Sections
        'section', 'subsection', 'subsubsection', 'paragraph', 'subparagraph',
        'section*', 'subsection*', 'subsubsection*',
        # Text formatting
        'textbf', 'textit', 'textsc', 'textsl', 'emph', 'underline',
        'textmd', 'textsf', 'texttt', 'textrm', 'textnormal',
        # Lists
        'itemize', 'enumerate', 'description', 'item',
        # Math (standard LaTeX math commands)
        'text', 'mbox', 'fbox',
        'cdot', 'times', 'div', 'pm', 'mp', 'ast', 'star',
        'leq', 'geq', 'neq', 'approx', 'equiv', 'sim',
        'sum', 'prod', 'int', 'oint', 'partial',
        'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta', 'theta',
        'iota', 'kappa', 'lambda', 'mu', 'nu', 'xi', 'pi', 'rho', 'sigma',
        'tau', 'upsilon', 'phi', 'chi', 'psi', 'omega',
        'Gamma', 'Delta', 'Theta', 'Lambda', 'Xi', 'Pi', 'Sigma',
        'Upsilon', 'Phi', 'Psi', 'Omega',
        'infty', 'nabla', 'forall', 'exists', 'emptyset', 'in', 'notin',
        'subset', 'subseteq', 'supset', 'supseteq', 'cup', 'cap', 'setminus',
        'wedge', 'vee', 'oplus', 'ominus', 'otimes', 'oslash',
        'leftarrow', 'rightarrow', 'leftrightarrow', 'Leftarrow', 'Rightarrow',
        'Leftrightarrow', 'uparrow', 'downarrow', 'updownarrow',
        'left', 'right', 'middle', 'big', 'Big', 'bigg', 'Bigg',
        'sqrt', 'frac', 'binom', 'choose',
        # Spacing
        'vspace', 'hspace', 'vfill', 'hfill', 'newline', 'linebreak',
        'pagebreak', 'newpage', 'clearpage',
        # Fonts
        'tiny', 'scriptsize', 'footnotesize', 'small', 'normalsize',
        'large', 'Large', 'LARGE', 'huge', 'Huge',
        'rmfamily', 'sffamily', 'ttfamily',
        # Colors (basic)
        'textcolor', 'color',
        # URLs and references
        'href', 'url', 'nolinkurl', 'label', 'ref', 'pageref',
        # Tables
        'tabular', 'table', 'caption', 'hline', 'cline',
        # Other common commands
        'centering', 'raggedright', 'raggedleft',
        'par', 'noindent', 'indent',
        'today', 'maketitle', 'title', 'author', 'date',
        'input', 'include', 'includeonly',
        'newcommand', 'renewcommand', 'providecommand', 'def',
        'newcommand*', 'renewcommand*', 'providecommand*',
        'DeclareRobustCommand', 'DeclareTextFontCommand',
        'usepackage', 'RequirePackage',
        'pagestyle', 'thispagestyle',
        'setlength', 'addtolength', 'newlength',
        'renewcommand', 'newcommand',
        'definecolor', 'DeclareRobustCommand',
        'DeclareTextFontCommand',
        # Text symbols (available in base LaTeX or common packages)
        # Note: \textbullet requires textcomp package, but we'll allow it as it's commonly available
        'textbullet', 'textasteriskcentered', 'textperiodcentered',
    }
    
    # Packages that are typically available in LaTeX distributions
    # This should be updated based on what's actually in the LaTeX image
    COMMON_PACKAGES = {
        'inputenc', 'geometry', 'enumitem', 'hyperref', 'fullpage',
        'titlesec', 'marvosym', 'color', 'xcolor', 'verbatim',
        'fancyhdr', 'babel', 'tabularx', 'fontawesome5', 'FiraMono',
        'contour', 'ulem', 'tgheros', 'fontenc', 'latexsym',
        'amsmath', 'amssymb', 'graphicx', 'pdfpages',
    }
    
    def validate(self, source: str) -> ValidationResult:
        """
        Validate LaTeX source code.
        
        Args:
            source: LaTeX source code to validate
            
        Returns:
            ValidationResult with errors if any
        """
        errors: List[ValidationError] = []
        
        # Split into lines for line number tracking
        lines = source.split('\n')
        
        # 1. Check bracket balance
        bracket_error = self._check_bracket_balance(source, lines)
        if bracket_error:
            errors.append(bracket_error)
        
        # 2. Check environment balance
        env_errors = self._check_environment_balance(source, lines)
        errors.extend(env_errors)
        
        # 3. Check list structure
        list_errors = self._check_list_structure(source, lines)
        errors.extend(list_errors)
        
        # 4. Check document structure
        doc_error = self._check_document_structure(source)
        if doc_error:
            errors.append(doc_error)
        
        # 5. Check for forbidden commands
        forbidden_errors = self._check_forbidden_commands(source, lines)
        errors.extend(forbidden_errors)
        
        # 6. Check for undefined control sequences (heuristic)
        undefined_errors = self._check_undefined_commands(source, lines)
        errors.extend(undefined_errors)
        
        # 7. Check math mode balance
        math_errors = self._check_math_mode_balance(source, lines)
        errors.extend(math_errors)
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors
        )
    
    def _check_bracket_balance(self, source: str, lines: List[str]) -> Optional[ValidationError]:
        """Check if braces {} are balanced."""
        depth = 0
        max_depth = 0
        last_open_pos = None
        
        # Track position
        char_pos = 0
        
        for i, char in enumerate(source):
            if char == '{':
                # Skip if escaped
                if i > 0 and source[i-1] == '\\':
                    continue
                depth += 1
                if depth > max_depth:
                    max_depth = depth
                    last_open_pos = char_pos
            elif char == '}':
                # Skip if escaped
                if i > 0 and source[i-1] == '\\':
                    continue
                depth -= 1
                if depth < 0:
                    # Too many closing braces
                    line_num, char_offset = self._get_line_position(source, i)
                    context = self._get_context(source, i, 50)
                    return ValidationError(
                        error_type=ValidationErrorType.BRACKET_MISMATCH,
                        message=f"Too many closing braces '}}' at position {i}",
                        line_number=line_num,
                        char_offset=char_offset,
                        context=context
                    )
            char_pos += 1
        
        if depth > 0:
            # Unclosed braces
            line_num, char_offset = self._get_line_position(source, last_open_pos if last_open_pos else len(source) - 1)
            context = self._get_context(source, last_open_pos if last_open_pos else len(source) - 1, 50)
            return ValidationError(
                error_type=ValidationErrorType.BRACKET_MISMATCH,
                message=f"Unclosed braces: {depth} opening brace(s) not closed",
                line_number=line_num,
                char_offset=char_offset,
                context=context
            )
        
        return None
    
    def _check_environment_balance(self, source: str, lines: List[str]) -> List[ValidationError]:
        """Check if \begin{...} and \end{...} environments are balanced and matched."""
        errors: List[ValidationError] = []
        
        # Find all \begin{env} and \end{env}
        begin_pattern = r'\\begin\{([^}]+)\}'
        end_pattern = r'\\end\{([^}]+)\}'
        
        begins = []
        ends = []
        
        for match in re.finditer(begin_pattern, source):
            env_name = match.group(1)
            line_num, char_offset = self._get_line_position(source, match.start())
            begins.append((env_name, match.start(), line_num, char_offset))
        
        for match in re.finditer(end_pattern, source):
            env_name = match.group(1)
            line_num, char_offset = self._get_line_position(source, match.start())
            ends.append((env_name, match.start(), line_num, char_offset))
        
        # Normalize environment names for matching (handle variants like tightitemize -> itemize)
        def normalize_env_name(name: str) -> str:
            """Normalize environment names to standard forms."""
            name_lower = name.lower()
            if 'itemize' in name_lower or 'tightitemize' in name_lower or 'compactitemize' in name_lower:
                return 'itemize'
            elif 'enumerate' in name_lower or 'compactenumerate' in name_lower:
                return 'enumerate'
            elif 'description' in name_lower:
                return 'description'
            return name
        
        # Check balance using a stack
        env_stack = []
        begin_map = {pos: (name, line, offset) for name, pos, line, offset in begins}
        end_map = {pos: (name, line, offset) for name, pos, line, offset in ends}
        
        all_positions = sorted(set(begin_map.keys()) | set(end_map.keys()))
        
        for pos in all_positions:
            if pos in begin_map:
                env_name, line_num, char_offset = begin_map[pos]
                env_stack.append((env_name, pos, line_num, char_offset))
            elif pos in end_map:
                env_name, line_num, char_offset = end_map[pos]
                if not env_stack:
                    context = self._get_context(source, pos, 50)
                    errors.append(ValidationError(
                        error_type=ValidationErrorType.ENVIRONMENT_MISMATCH,
                        message=f"\\end{{{env_name}}} without matching \\begin",
                        line_number=line_num,
                        char_offset=char_offset,
                        context=context
                    ))
                else:
                    expected_name, expected_pos, expected_line, expected_offset = env_stack.pop()
                    normalized_expected = normalize_env_name(expected_name)
                    normalized_actual = normalize_env_name(env_name)
                    
                    # Check for mismatched environments
                    if normalized_expected != normalized_actual:
                        context = self._get_context(source, pos, 50)
                        errors.append(ValidationError(
                            error_type=ValidationErrorType.ENVIRONMENT_MISMATCH,
                            message=f"\\end{{{env_name}}} does not match \\begin{{{expected_name}}} (line {expected_line}). Expected \\end{{{expected_name}}}",
                            line_number=line_num,
                            char_offset=char_offset,
                            context=context
                        ))
                    elif expected_name != env_name and normalized_expected == normalized_actual:
                        # Same normalized name but different actual names (e.g., tightitemize vs itemize)
                        # This is a warning but will be auto-fixed
                        context = self._get_context(source, pos, 50)
                        errors.append(ValidationError(
                            error_type=ValidationErrorType.ENVIRONMENT_MISMATCH,
                            message=f"\\end{{{env_name}}} does not exactly match \\begin{{{expected_name}}} (line {expected_line}). Should be \\end{{{expected_name}}}",
                            line_number=line_num,
                            char_offset=char_offset,
                            context=context
                        ))
        
        # Check for unclosed environments
        for env_name, pos, line_num, char_offset in env_stack:
            context = self._get_context(source, pos, 50)
            errors.append(ValidationError(
                error_type=ValidationErrorType.ENVIRONMENT_MISMATCH,
                message=f"\\begin{{{env_name}}} not closed",
                line_number=line_num,
                char_offset=char_offset,
                context=context
            ))
        
        return errors
    
    def _check_list_structure(self, source: str, lines: List[str]) -> List[ValidationError]:
        """
        Check list structure: \item must be inside list environments.
        
        This is a relaxed check that allows \item in macro definitions and
        uses a more robust algorithm to detect list environments.
        """
        errors: List[ValidationError] = []
        
        # Find all \item commands
        item_pattern = r'\\item\b'
        
        # Find all list environments
        list_envs = ['itemize', 'enumerate', 'description']
        
        # Build a list of (begin_pos, end_pos) pairs for each list environment
        list_ranges = []
        
        for env_name in list_envs:
            begin_pattern = rf'\\begin\{{{re.escape(env_name)}\}}'
            end_pattern = rf'\\end\{{{re.escape(env_name)}\}}'
            
            # Find all begin/end pairs using a stack-based approach
            begins = []
            for match in re.finditer(begin_pattern, source):
                begins.append((match.start(), match.end()))
            
            ends = []
            for match in re.finditer(end_pattern, source):
                ends.append((match.start(), match.end()))
            
            # Match begins with ends using a stack
            stack = []
            begin_idx = 0
            end_idx = 0
            
            while begin_idx < len(begins) or end_idx < len(ends):
                if begin_idx < len(begins) and (end_idx >= len(ends) or begins[begin_idx][0] < ends[end_idx][0]):
                    # Process begin
                    stack.append(begins[begin_idx])
                    begin_idx += 1
                else:
                    # Process end
                    if stack:
                        begin_pos, begin_end_pos = stack.pop()
                        end_pos = ends[end_idx][0]
                        list_ranges.append((begin_end_pos, end_pos))
                    end_idx += 1
        
        # Sort ranges by start position
        list_ranges.sort(key=lambda x: x[0])
        
        # Check \item commands
        for match in re.finditer(item_pattern, source):
            item_pos = match.start()
            
            # Skip if \item is inside a macro definition (between \newcommand and the closing brace)
            # Check if we're inside a \newcommand definition
            lookback_start = max(0, item_pos - 2000)
            lookback_text = source[lookback_start:item_pos]
            
            # Check if there's a \newcommand, \renewcommand, or \providecommand before this
            # and if we're still inside its definition
            cmd_def_match = None
            for cmd_type in ['newcommand', 'renewcommand', 'providecommand', 'def']:
                pattern = rf'\\(?:{cmd_type})\*?(?:\[[^\]]*\])?\{{([^}}]+)\}}'
                matches = list(re.finditer(pattern, lookback_text))
                if matches:
                    # Check the most recent one
                    last_match = matches[-1]
                    # The command name is captured, but we need to find where the definition ends
                    # This is heuristic - look for the closing brace of the definition
                    # For simplicity, skip items that are clearly in macro definitions
                    cmd_def_match = last_match
                    break
            
            # If we're likely inside a macro definition, skip this check
            # (Macro definitions can contain \item which will be valid when expanded)
            if cmd_def_match:
                # Check if there are unmatched braces after the command definition start
                # This is a heuristic - if we find the item very close to a command definition,
                # it's likely part of the definition
                continue
            
            # Check if this \item is inside any list environment
            is_inside_list = False
            for begin_pos, end_pos in list_ranges:
                if begin_pos <= item_pos < end_pos:
                    is_inside_list = True
                    break
            
            if not is_inside_list:
                # More lenient check: look for \begin{itemize} etc. in a wider range
                # This handles cases where the list environment might be far away
                # (e.g., in template macros that expand)
                lookback_start = max(0, item_pos - 2000)
                lookback_text = source[lookback_start:item_pos]
                
                # Also look forward a bit in case the begin is after
                lookahead_end = min(len(source), item_pos + 500)
                lookahead_text = source[item_pos:lookahead_end]
                
                # Check for list environments in lookback
                has_list_start = bool(re.search(r'\\begin\{(itemize|enumerate|description)\}', lookback_text))
                
                # Check for custom list start commands (template-specific)
                has_custom_list_start = bool(re.search(
                    r'\\(resumeSubHeadingListStart|resumeItemListStart|begin\{itemize)',
                    lookback_text
                ))
                
                # Only report error if we're confident it's actually outside a list
                # Be lenient - many templates use \item in macros that expand correctly
                if not has_list_start and not has_custom_list_start:
                    # Double-check: look for any \begin{...} that might be a list
                    # This is a fallback for edge cases
                    any_begin = re.search(r'\\begin\{[^}]+\}', lookback_text)
                    if any_begin:
                        # Might be inside some environment, be lenient
                        continue
                    
                    line_num, char_offset = self._get_line_position(source, item_pos)
                    context = self._get_context(source, item_pos, 50)
                    errors.append(ValidationError(
                        error_type=ValidationErrorType.LIST_STRUCTURE_ERROR,
                        message="\\item found outside list environment (itemize, enumerate, or description)",
                        line_number=line_num,
                        char_offset=char_offset,
                        context=context
                    ))
        
        return errors
    
    def _check_document_structure(self, source: str) -> Optional[ValidationError]:
        """Check for required document structure."""
        has_documentclass = bool(re.search(r'\\documentclass', source))
        has_begin_document = bool(re.search(r'\\begin\{document\}', source))
        has_end_document = bool(re.search(r'\\end\{document\}', source))
        
        if not has_documentclass:
            return ValidationError(
                error_type=ValidationErrorType.MISSING_DOCUMENT_STRUCTURE,
                message="Missing \\documentclass declaration",
                line_number=1,
                char_offset=0,
                context=source[:100] if len(source) > 100 else source
            )
        
        if not has_begin_document:
            return ValidationError(
                error_type=ValidationErrorType.MISSING_DOCUMENT_STRUCTURE,
                message="Missing \\begin{document}",
                line_number=None,
                char_offset=None,
                context=None
            )
        
        if not has_end_document:
            return ValidationError(
                error_type=ValidationErrorType.MISSING_DOCUMENT_STRUCTURE,
                message="Missing \\end{document}",
                line_number=None,
                char_offset=None,
                context=None
            )
        
        return None
    
    def _check_forbidden_commands(self, source: str, lines: List[str]) -> List[ValidationError]:
        """Check for forbidden commands (security)."""
        errors: List[ValidationError] = []
        
        for pattern, description in self.FORBIDDEN_PATTERNS:
            for match in re.finditer(pattern, source, re.IGNORECASE):
                line_num, char_offset = self._get_line_position(source, match.start())
                context = self._get_context(source, match.start(), 50)
                errors.append(ValidationError(
                    error_type=ValidationErrorType.FORBIDDEN_COMMAND,
                    message=f"Forbidden command detected: {description}",
                    line_number=line_num,
                    char_offset=char_offset,
                    context=context
                ))
        
        return errors
    
    def _check_undefined_commands(self, source: str, lines: List[str]) -> List[ValidationError]:
        """
        Heuristic check for undefined control sequences.
        
        This is a best-effort check. It looks for \commands that:
        1. Are not in the standard commands whitelist
        2. Are not defined via \newcommand, \renewcommand, etc.
        3. Are not package-provided commands (heuristically)
        """
        errors: List[ValidationError] = []
        
        # Extract all defined commands
        defined_commands = set()
        
        # Find \newcommand, \renewcommand, \providecommand definitions
        command_def_pattern = r'\\(?:new|renew|provide)command\*?(?:\[[^\]]*\])?\{([^}]+)\}'
        for match in re.finditer(command_def_pattern, source):
            cmd_name = match.group(1)
            defined_commands.add(cmd_name)
        
        # Find \def definitions
        def_pattern = r'\\def\\([a-zA-Z@]+)'
        for match in re.finditer(def_pattern, source):
            cmd_name = match.group(1)
            defined_commands.add(cmd_name)
        
        # Extract loaded packages to whitelist their commands
        loaded_packages = set()
        package_pattern = r'\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}'
        for match in re.finditer(package_pattern, source):
            packages_str = match.group(1)
            # Handle comma-separated packages
            packages = [p.strip() for p in packages_str.split(',')]
            loaded_packages.update(packages)
        
        # Commands from common packages
        package_commands = {
            # hyperref package commands
            'hyperref': {'nolinkurl', 'href', 'url', 'hyperref', 'pdfstartlink', 'pdfendlink',
                        'autoref', 'nameref', 'phantomsection', 'hypersetup'},
            # titlesec package commands
            'titlesec': {'titleformat', 'titlespacing', 'titlelabel', 'titleline'},
            # enumitem package commands
            'enumitem': {'setlist', 'newlist', 'renewlist', 'setlist'},
            # fancyhdr package commands
            'fancyhdr': {'fancyhead', 'fancyfoot', 'fancyhf', 'fancypagestyle'},
            # fontawesome5 package commands
            'fontawesome5': {'faPhone', 'faEnvelope', 'faLink', 'faMapMarker', 'faGithub',
                           'faLinkedin', 'faTwitter', 'faGlobe'},
            # ulem package commands
            'ulem': {'uline', 'uuline', 'uwave', 'sout', 'xout'},
            # contour package commands
            'contour': {'contour', 'contourlength'},
            # tabularx package commands
            'tabularx': {'tabularx', 'tabularx*'},
            # geometry package commands
            'geometry': {'geometry', 'newgeometry', 'restoregeometry'},
        }
        
        # Build whitelist of package-provided commands
        package_command_whitelist = set()
        for package in loaded_packages:
            if package in package_commands:
                package_command_whitelist.update(package_commands[package])
        
        # Template-specific commands that are commonly used
        template_commands = {
            'resumeItem', 'resumeSubheading', 'resumeSubSubheading', 'resumeProjectHeading',
            'resumeSubItem', 'resumeSubHeadingListStart', 'resumeSubHeadingListEnd',
            'resumeItemListStart', 'resumeItemListEnd', 'resumesection',  # Common template command
            'myuline', 'texteb', 'ebseries',  # From main template
            'FullName', 'Email', 'Phone', 'Address', 'LinkedIn', 'GitHub', 'Website', 'ProfilePhoto',  # From ATS template
            # AI agent sometimes generates these (should use \section* instead, but whitelist to prevent false positives)
            'sectiontitle', 'sectionTitle', 'SectionTitle',
        }
        
        # Find all \command patterns
        command_pattern = r'\\([a-zA-Z@]+)'
        
        for match in re.finditer(command_pattern, source):
            cmd_name = match.group(1)
            
            # Skip if it's a standard command
            if cmd_name in self.STANDARD_COMMANDS:
                continue
            
            # Skip if it's defined in the document
            if cmd_name in defined_commands:
                continue
            
            # Skip if it's a template command
            if cmd_name in template_commands:
                continue
            
            # Skip if it's a package-provided command
            if cmd_name in package_command_whitelist:
                continue
            
            # Skip if it's part of a command definition
            # Check if we're inside a \newcommand, etc.
            match_start = match.start()
            lookback = source[max(0, match_start - 100):match_start]
            if re.search(r'\\(?:new|renew|provide)command', lookback):
                continue
            
            # Skip package commands (heuristically - this is imperfect)
            # Check if there's a \usepackage before this command
            preamble_end = source.find('\\begin{document}')
            if preamble_end == -1:
                preamble_end = len(source)
            
            if match_start < preamble_end:
                # In preamble, likely a package command
                continue
            
            # This might be an undefined command
            # Only flag if it's in the document body and looks suspicious
            line_num, char_offset = self._get_line_position(source, match_start)
            context = self._get_context(source, match_start, 50)
            
            # Don't flag common false positives
            false_positives = {'documentclass', 'usepackage', 'RequirePackage', 'inputenc',
                              'geometry', 'enumitem', 'hyperref', 'begin', 'end'}
            if cmd_name.lower() in false_positives:
                continue
            
            errors.append(ValidationError(
                error_type=ValidationErrorType.UNDEFINED_COMMAND,
                message=f"Potentially undefined control sequence: \\{cmd_name}",
                line_number=line_num,
                char_offset=char_offset,
                context=context
            ))
        
        return errors
    
    def _check_math_mode_balance(self, source: str, lines: List[str]) -> List[ValidationError]:
        """
        Check if math mode delimiters ($ and $$) are balanced.
        
        LaTeX has two types of math mode:
        - Inline math: $...$ (single dollar signs)
        - Display math: $$...$$ (double dollar signs)
        Both must be balanced.
        """
        errors: List[ValidationError] = []
        
        # Check display math ($$...$$)
        double_dollar_count = source.count('$$')
        if double_dollar_count % 2 != 0:
            # Find the last $$ position
            last_pos = source.rfind('$$')
            line_num, char_offset = self._get_line_position(source, last_pos)
            context = self._get_context(source, last_pos, 50)
            errors.append(ValidationError(
                error_type=ValidationErrorType.BRACKET_MISMATCH,
                message=f"Unbalanced display math delimiters: {double_dollar_count} $$ found (must be even). Display math should end with $$.",
                line_number=line_num,
                char_offset=char_offset,
                context=context
            ))
        
        # Check inline math ($...$) - but exclude $$ pairs
        # Replace $$ with placeholder to count only single $
        placeholder = '___DOUBLE_DOLLAR_PLACEHOLDER___'
        temp_source = source.replace('$$', placeholder)
        
        single_dollar_count = temp_source.count('$')
        if single_dollar_count % 2 != 0:
            # Find the last $ position
            last_pos = temp_source.rfind('$')
            # Convert back to original position
            original_pos = source.rfind('$')
            if original_pos != -1:
                line_num, char_offset = self._get_line_position(source, original_pos)
                context = self._get_context(source, original_pos, 50)
                errors.append(ValidationError(
                    error_type=ValidationErrorType.BRACKET_MISMATCH,
                    message=f"Unbalanced inline math delimiters: {single_dollar_count} $ found (must be even). Inline math should end with $.",
                    line_number=line_num,
                    char_offset=char_offset,
                    context=context
                ))
        
        return errors
    
    def _get_line_position(self, source: str, char_pos: int) -> Tuple[int, int]:
        """Get line number and character offset for a character position."""
        lines = source[:char_pos].split('\n')
        line_number = len(lines)
        char_offset = len(lines[-1]) if lines else 0
        return line_number, char_offset
    
    def _get_context(self, source: str, pos: int, context_size: int = 50) -> str:
        """Get context around a position."""
        start = max(0, pos - context_size)
        end = min(len(source), pos + context_size)
        context = source[start:end]
        # Replace newlines with spaces for readability
        context = context.replace('\n', ' ')
        return context


# Singleton instance
latex_validator = LaTeXValidator()
