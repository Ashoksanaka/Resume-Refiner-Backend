# ATS-Friendly Professional Resume Template

## Overview

This is a production-ready LaTeX resume template designed specifically for automated generation in SaaS environments. The template prioritizes ATS (Applicant Tracking System) compatibility, clean parsing, and reliable compilation over visual complexity.

**Version:** 1.0.0  
**Engine:** pdflatex  
**Target Environment:** Dockerized TeX Live

## Quick Start

### Compilation

```bash
pdflatex -interaction=nonstopmode template.tex
```

Expected compile time: 3-5 seconds for typical resume content.

### Basic Integration Pattern

```latex
% 1. Set personal information
\FullName{John Doe}
\Email{john.doe@email.com}
\Phone{+1 (555) 123-4567}

% 2. Add experience entries
\ExperienceItem{Company Name}{Job Title}{Start Date}{End Date}{Location}{%
  \item First responsibility or achievement
  \item Second responsibility or achievement
  \item Third responsibility or achievement
}

% 3. Render the document
\RenderHeader
\RenderSections
```

## Architecture

### Design Philosophy

The template uses a **macro-based injection system** with conditional rendering. Each section has associated boolean flags that control visibility. When no data is injected for a section, it collapses completely without leaving whitespace or visual artifacts.

### Core Components

**Header System:** The `\RenderHeader` command generates the contact information block at the top of the resume. All personal information fields are optional except for full name.

**Section Control:** Each major section has an associated boolean flag (e.g., `\showexperiencetrue`) that is automatically set when data is added. The `\RenderSections` command checks these flags and only renders populated sections.

**Content Storage:** Section content is accumulated in internal macros (e.g., `\@experiencecontent`) using the `\gappto` command, which appends content globally. This allows multiple items to be added to the same section.

## Complete Field Reference

### Personal Information

All personal information fields are optional except `\FullName`. The header will adapt based on which fields are provided. The `\ProfilePhoto` macro is defined for completeness but is not rendered in the template output.

**Important ATS Consideration:** Profile photos are generally discouraged for ATS-submitted resumes. Many applicant tracking systems ignore image content entirely, and in some jurisdictions, inclusion of photos may raise compliance concerns. The profile photo macro is provided for compatibility with systems that may accept it, but resumes will function perfectly without it, and layout is completely unaffected by its presence or absence.

```latex
\FullName{Full Name}              % Required
\Email{email@example.com}         % Optional
\Phone{+1 (555) 123-4567}        % Optional  
\Address{City, State}             % Optional
\LinkedIn{linkedin.com/in/user}   % Optional
\GitHub{github.com/user}          % Optional
\Website{website.com}             % Optional
```

### Professional Summary

The professional summary is a brief paragraph describing the candidate's expertise and career focus.

```latex
\ProfessionalSummary{Your summary text here...}
\showsummarytrue  % Must be called to display section
```

### Experience Section

Experience items include company, role, dates, location, and bullet-pointed responsibilities. The location parameter is optional.

```latex
\ExperienceItem{Company Name}{Job Title}{Start Date}{End Date}{Location}{%
  \item Responsibility or achievement one
  \item Responsibility or achievement two
  \item Responsibility or achievement three
}
```

**Parameter Details:**
- Parameter 1: Company name
- Parameter 2: Job title or role
- Parameter 3: Start date (e.g., "January 2020")
- Parameter 4: End date (e.g., "Present" or "December 2023")
- Parameter 5: Location (can be empty: `{}`)
- Parameter 6: Bullet points using `\item` commands

### Education Section

Education entries include institution, degree, field of study, dates, and optional notes.

```latex
\EducationItem{Institution}{Degree}{Field of Study}{Start Date}{End Date}{Notes}
```

**Example:**
```latex
\EducationItem{University Name}{Bachelor of Science}{Computer Science}{Aug 2016}{May 2020}{GPA: 3.8/4.0}
```

The field of study and notes parameters can be left empty using `{}` if not applicable.

### Projects Section

The template provides two macros for projects depending on whether a URL is included.

**Standard project (no link):**
```latex
\ProjectItem{Project Title}{Your Role}{Start Date}{End Date}{Description paragraph}
```

**Project with link:**
```latex
\ProjectItemWithLink{Project Title}{Your Role}{Start Date}{End Date}{Description}{project-url.com}
```

The role parameter can be empty if not applicable.

### Certifications Section

Certifications can be added with or without additional notes.

**Standard certification:**
```latex
\CertificationItem{Certification Name}{Issuing Organization}{Date Obtained}
```

**Certification with notes:**
```latex
\CertificationItemWithNotes{Certification Name}{Issuing Organization}{Date}{Additional context or description}
```

### Achievements Section

Achievements follow a similar pattern with optional descriptions.

**Standard achievement:**
```latex
\AchievementItem{Achievement Title}{Context or Event}{Date}
```

**Achievement with description:**
```latex
\AchievementItemWithDesc{Achievement Title}{Context}{Date}{Detailed description}
```

### Publications Section

Publications include title, journal or venue, date, and brief description.

```latex
\PublicationItem{Paper Title}{Journal Name, Volume/Issue}{Date}{Brief description}
```

### Patents Section

Patent entries require title, patent number, date, and description.

```latex
\PatentItem{Patent Title}{Patent Number (e.g., US10234567B2)}{Date}{Description}
```

### Volunteering Section

Volunteering activities include organization, role, date range, and description.

```latex
\VolunteeringItem{Organization Name}{Role or Position}{Date Range}{Description of activities}
```

### Licenses Section

Professional licenses can be added with or without notes.

**Standard license:**
```latex
\LicenseItem{License Name}{Issuing Authority}{Expiration or Issue Date}
```

**License with notes:**
```latex
\LicenseItemWithNotes{License Name}{Issuing Authority}{Date}{Additional information}
```

### Training and Courses Section

Training entries support optional notes for additional context.

**Standard training:**
```latex
\TrainingItem{Course Name}{Provider}{Completion Date}
```

**Training with notes:**
```latex
\TrainingItemWithNotes{Course Name}{Provider}{Date}{Course details or outcomes}
```

### Test Scores Section

Test scores display the test name, score, and date taken.

```latex
\TestScoreItem{Test Name}{Score Details}{Date Taken}
```

**Example:**
```latex
\TestScoreItem{GRE}{Quantitative: 170, Verbal: 165}{December 2020}
```

### Languages Section

Language proficiency entries are simple two-parameter commands.

```latex
\LanguageItem{Language Name}{Proficiency Level}
```

**Example:**
```latex
\LanguageItem{Spanish}{Professional working proficiency}
```

### Organizations Section

Professional organization memberships include name, role, dates, and description.

```latex
\OrganizationItem{Organization Name}{Membership Type or Role}{Date Range}{Description}
```

### Positions of Responsibility Section

This section captures leadership roles and responsibilities.

```latex
\PositionItem{Organization}{Position Title}{Date Range}{Description of responsibilities}
```

### Career Breaks Section

Career breaks are documented with start date, end date, and reason.

```latex
\CareerBreakItem{Start Date}{End Date}{Reason for break}
```

**Example:**
```latex
\CareerBreakItem{June 2020}{September 2020}{Sabbatical for family care and professional development}
```

## Backend Integration Guide

### Data Escaping Requirements

Your backend must escape the following LaTeX special characters before injection:

- Ampersand: `&` → `\&`
- Percent: `%` → `\%`
- Dollar sign: `$` → `\$`
- Hash: `#` → `\#`
- Underscore: `_` → `\_`
- Braces: `{` `}` → `\{` `\}`
- Tilde: `~` → `\textasciitilde{}`
- Caret: `^` → `\textasciicircum{}`
- Backslash: `\` → `\textbackslash{}`

### Recommended Injection Workflow

The backend should follow this pattern when generating a resume:

1. Start with the base template file
2. Locate the data injection area (marked with comments in template.tex)
3. Generate macro calls based on user profile data
4. Inject macro calls into the template
5. Call `\RenderHeader` and `\RenderSections`
6. Compile using pdflatex

### Handling Optional Fields

When a field is optional (such as location in experience items or notes in certifications), pass empty braces `{}` if no data is available. The template will handle this gracefully.

**Example with missing location:**
```latex
\ExperienceItem{TechCorp}{Software Engineer}{Jan 2020}{Present}{}{%
  \item Built scalable APIs
}
```

### Handling Empty Sections

If a user has no data for an entire section (e.g., no patents), simply omit all macro calls for that section. The section will not appear in the rendered document, and no whitespace will be left behind.

## ATS Compliance Details

### Layout Characteristics

This template uses a single-column layout with no tables for structural positioning. All content flows in natural reading order, which is critical for ATS parsing accuracy.

### Section Headings

All section headings are plain text rendered using LaTeX's section commands. This ensures ATS systems can identify section boundaries reliably.

### Lists and Bullets

Bullet points use standard LaTeX `itemize` environments with no custom symbols or formatting that might confuse parsers. The `enumitem` package provides consistent spacing while maintaining compatibility.

### URLs and Links

All URLs are rendered as plain text with the `hidelinks` option in hyperref. This ensures that links are visible and parseable by ATS systems while remaining clickable in PDF viewers.

### Font and Spacing

The template uses standard LaTeX fonts at readable sizes (11pt base). Line spacing and margins are optimized for both human readability and machine parsing.

### Known ATS Compatibility

This template has been designed with the parsing logic of the following ATS systems in mind:

- Workday
- Greenhouse  
- Lever
- Taleo
- iCIMS

While we cannot guarantee perfect parsing in every ATS (systems vary in quality), the template follows all documented best practices for ATS compatibility.

## Customization and Styling

### Modifying Section Order

Section order can be changed by reordering the conditional blocks in the `\RenderSections` command. Simply move the `\ifshowsection` blocks to your desired sequence.

### Adjusting Spacing

Vertical spacing between items can be modified by changing the `\vspace{}` commands at the end of each item macro. The current values (typically 4pt or 6pt) provide good balance between density and readability.

### Color Modifications

While the current template uses black for all text (optimal for ATS), you can modify the `sectioncolor` definition if you need subtle color accents. However, ensure sufficient contrast for both screen readers and printed copies.

## Troubleshooting

### Compilation Errors

**Error: Undefined control sequence**  
This typically means a macro was called before being defined or a special character was not properly escaped. Verify all user input is properly escaped.

**Error: Missing } inserted**  
Check that all macro parameters are properly enclosed in braces and that no unescaped braces appear in user content.

**Error: Package not found**  
Ensure your TeX Live installation includes all required packages listed in meta.json. Run `tlmgr update --self --all` to update your distribution.

### Formatting Issues

**Overlapping text or content**  
This may occur if descriptions are extremely long without natural break points. Consider implementing soft hyphens or breaking very long words.

**Inconsistent spacing**  
Verify that all item macros end with consistent `\vspace{}` commands and that no additional spacing is being injected by the backend.

### ATS Parsing Problems

**Content not detected by ATS**  
Ensure section headings match expected terms (e.g., "Experience" not "Work History"). Test with multiple ATS platforms as parsing quality varies significantly.

**Dates not recognized**  
Use consistent date formats throughout (e.g., "January 2020" or "Jan 2020", not mixed formats). Avoid unusual separators or ambiguous formats.

## Performance Considerations

### Compilation Time

Expected compile time for a typical two-page resume is 3-5 seconds. Factors that may increase compilation time include:

- Very long bullet lists (20+ items per section)
- Many sections with numerous entries
- Long URLs that require complex line breaking
- Special characters requiring extensive escaping

If compilation consistently exceeds 10 seconds, investigate potential causes such as infinite loops in content or package conflicts.

### Resource Usage

Memory usage should remain under 100MB for typical resume content. If you encounter out-of-memory errors, check for:

- Recursive macro definitions
- Extremely large text blocks without paragraph breaks
- Accidental inclusion of binary data in text fields

## Testing Recommendations

### Unit Testing

Test each section type independently with various data patterns:

- Minimum required fields only
- All optional fields populated
- Edge cases (very long text, special characters, URLs)
- Empty/null values

### Integration Testing

Test complete resumes with:

- All 17 sections populated
- Only required sections (Experience, Education)
- Mixed populated and empty sections
- Various content lengths (1 page, 2 pages, 3 pages)

### ATS Validation

Upload compiled PDFs to test ATS environments and verify:

- All sections are detected correctly
- Dates are parsed accurately
- Contact information is extracted properly
- Bullet points are preserved
- Section content is not scrambled

## Support and Maintenance

### Version History

**Version 1.0.1 (Current)**
- Refined xcolor package usage for improved ATS compatibility
- Enhanced paragraph spacing for better readability
- Explicit hyperlink styling neutralization
- Documented profile photo handling and ATS considerations
- Confirmed plain-text career break formatting

**Version 1.0.0**
- Initial production release
- Support for all 17 required sections
- Full ATS compliance
- Macro-based injection system
- Tested with pdflatex on TeX Live

### Future Enhancements

Potential improvements for future versions may include:

- Optional two-column layouts for academic CVs
- Additional language support for international markets
- Profile photo integration with proper positioning
- Alternative section styling options
- Enhanced date formatting macros

### Contributing

If your team identifies issues or improvements, document them clearly with:

- Specific section or macro affected
- Sample input that causes the issue
- Expected vs actual output
- Suggested fix or workaround

## License

This template is provided for use within your SaaS platform. Standard usage terms apply as defined in your organization's internal licensing policy.

---

**Last Updated:** January 2026  
**Maintained By:** LaTeX Template Team  
**Contact:** For integration questions, consult your platform engineering team.