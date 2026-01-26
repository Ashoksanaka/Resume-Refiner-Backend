"""
Email service for the Resume AI platform.

Provides email sending functionality using SendGrid API.
Falls back to Django's default email backend if SendGrid is not configured.
"""

import logging
from typing import Optional
from django.conf import settings
from django.core.mail import send_mail as django_send_mail

logger = logging.getLogger(__name__)


class EmailService:
    """
    Email service that uses SendGrid API for sending emails.
    
    Features:
    - HTML and plain text email support
    - Template-based emails
    - Graceful fallback to Django's email backend
    - No PII in logs
    """
    
    def __init__(self):
        self.sendgrid_api_key = getattr(settings, 'SENDGRID_API_KEY', None)
        self.from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@resume-ai.com')
        self.from_name = getattr(settings, 'EMAIL_FROM_NAME', 'Resume AI')
        self.sendgrid_disabled = False  # Track if SendGrid should be disabled due to auth errors
        
        if self.sendgrid_api_key:
            try:
                from sendgrid import SendGridAPIClient
                self.sg_client = SendGridAPIClient(self.sendgrid_api_key)
                self.use_sendgrid = True
                logger.info("SendGrid email service initialized")
            except ImportError:
                logger.warning("SendGrid package not installed, falling back to Django email")
                self.use_sendgrid = False
        else:
            logger.info("SendGrid API key not configured, using Django email backend")
            self.use_sendgrid = False
    
    def send_email(
        self,
        to_email: str,
        subject: str,
        plain_text: str,
        html_content: Optional[str] = None,
    ) -> bool:
        """
        Send an email.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            plain_text: Plain text content
            html_content: Optional HTML content
        
        Returns:
            True if email was sent successfully, False otherwise
        """
        if self.use_sendgrid and not self.sendgrid_disabled:
            return self._send_via_sendgrid(to_email, subject, plain_text, html_content)
        else:
            return self._send_via_django(to_email, subject, plain_text, html_content)
    
    def _send_via_sendgrid(
        self,
        to_email: str,
        subject: str,
        plain_text: str,
        html_content: Optional[str] = None,
    ) -> bool:
        """Send email using SendGrid API."""
        from sendgrid.helpers.mail import Mail, Email, To, Content, HtmlContent
        
        try:
            message = Mail(
                from_email=Email(self.from_email, self.from_name),
                to_emails=To(to_email),
                subject=subject,
            )
            
            # Add plain text content
            message.add_content(Content("text/plain", plain_text))
            
            # Add HTML content if provided
            if html_content:
                message.add_content(Content("text/html", html_content))
            
            response = self.sg_client.send(message)
            
            if response.status_code in (200, 201, 202):
                logger.info("Email sent successfully via SendGrid (status: %d)", response.status_code)
                return True
            else:
                logger.error("SendGrid returned status %d", response.status_code)
                return False
                
        except Exception as e:
            error_type = type(e).__name__
            # Check if it's an authentication/authorization error (403, 401)
            is_auth_error = (
                'ForbiddenError' in error_type or 
                'UnauthorizedError' in error_type or
                '403' in str(e) or
                '401' in str(e)
            )
            
            if is_auth_error:
                logger.error(
                    "SendGrid authentication failed (403/401). This usually means: "
                    "1) Invalid API key, 2) Unverified sender email, or 3) Insufficient permissions. "
                    "Disabling SendGrid and falling back to Django email backend."
                )
                self.sendgrid_disabled = True  # Disable SendGrid for future requests
            else:
                logger.warning("Failed to send email via SendGrid: %s. Falling back to Django email backend.", error_type)
            
            # Fall back to Django email backend when SendGrid fails
            return self._send_via_django(to_email, subject, plain_text, html_content)
    
    def _send_via_django(
        self,
        to_email: str,
        subject: str,
        plain_text: str,
        html_content: Optional[str] = None,
    ) -> bool:
        """Send email using Django's email backend."""
        try:
            from django.core.mail import EmailMultiAlternatives
            
            email = EmailMultiAlternatives(
                subject=subject,
                body=plain_text,
                from_email=f"{self.from_name} <{self.from_email}>",
                to=[to_email],
            )
            
            if html_content:
                email.attach_alternative(html_content, "text/html")
            
            email.send(fail_silently=False)
            logger.info("Email sent successfully via Django backend")
            return True
            
        except Exception as e:
            logger.exception("Failed to send email via Django: %s", type(e).__name__)
            return False
    
    def send_verification_email(self, to_email: str, token: str, user_name: Optional[str] = None) -> bool:
        """
        Send email verification email.
        
        Args:
            to_email: Recipient email address
            token: Verification token
            user_name: Optional user name for personalization
        
        Returns:
            True if email was sent successfully
        """
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
        verification_url = f"{frontend_url}/verify?token={token}"
        
        subject = "Verify your Resume AI account"
        
        plain_text = f"""
Hello{' ' + user_name if user_name else ''},

Welcome to Resume AI! Please verify your email address by clicking the link below:

{verification_url}

This link will expire in 24 hours.

If you didn't create an account with Resume AI, please ignore this email.

Best regards,
The Resume AI Team
"""
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Verify your email</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 28px;">Resume AI</h1>
        <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0;">AI-Powered Resume Customization</p>
    </div>
    
    <div style="background: #ffffff; padding: 40px 30px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
        <h2 style="color: #333; margin-top: 0;">Verify your email address</h2>
        
        <p>Hello{' ' + user_name if user_name else ''},</p>
        
        <p>Welcome to Resume AI! You're just one step away from creating ATS-optimized resumes tailored to your dream jobs.</p>
        
        <p>Please click the button below to verify your email address:</p>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="{verification_url}" 
               style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 14px 40px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;">
                Verify Email Address
            </a>
        </div>
        
        <p style="color: #666; font-size: 14px;">Or copy and paste this link into your browser:</p>
        <p style="background: #f5f5f5; padding: 12px; border-radius: 6px; word-break: break-all; font-size: 13px; color: #555;">
            {verification_url}
        </p>
        
        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee;">
            <p style="color: #888; font-size: 13px; margin: 0;">
                <strong>Note:</strong> This link will expire in 24 hours.
            </p>
            <p style="color: #888; font-size: 13px;">
                If you didn't create an account with Resume AI, you can safely ignore this email.
            </p>
        </div>
    </div>
    
    <div style="text-align: center; padding: 20px; color: #888; font-size: 12px;">
        <p style="margin: 0;">&copy; 2026 Resume AI. All rights reserved.</p>
        <p style="margin: 5px 0 0 0;">Building better resumes with AI.</p>
    </div>
</body>
</html>
"""
        
        return self.send_email(to_email, subject, plain_text, html_content)
    
    def send_password_reset_email(self, to_email: str, token: str, user_name: Optional[str] = None) -> bool:
        """
        Send password reset email.
        
        Args:
            to_email: Recipient email address
            token: Password reset token
            user_name: Optional user name for personalization
        
        Returns:
            True if email was sent successfully
        """
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
        reset_url = f"{frontend_url}/reset-password?token={token}"
        
        subject = "Reset your Resume AI password"
        
        plain_text = f"""
Hello{' ' + user_name if user_name else ''},

We received a request to reset your password for your Resume AI account.

Click the link below to reset your password:

{reset_url}

This link will expire in 1 hour.

If you didn't request a password reset, please ignore this email. Your password will remain unchanged.

Best regards,
The Resume AI Team
"""
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reset your password</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 28px;">Resume AI</h1>
        <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0;">AI-Powered Resume Customization</p>
    </div>
    
    <div style="background: #ffffff; padding: 40px 30px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
        <h2 style="color: #333; margin-top: 0;">Reset your password</h2>
        
        <p>Hello{' ' + user_name if user_name else ''},</p>
        
        <p>We received a request to reset your password for your Resume AI account.</p>
        
        <p>Click the button below to set a new password:</p>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="{reset_url}" 
               style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 14px 40px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;">
                Reset Password
            </a>
        </div>
        
        <p style="color: #666; font-size: 14px;">Or copy and paste this link into your browser:</p>
        <p style="background: #f5f5f5; padding: 12px; border-radius: 6px; word-break: break-all; font-size: 13px; color: #555;">
            {reset_url}
        </p>
        
        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee;">
            <p style="color: #888; font-size: 13px; margin: 0;">
                <strong>Note:</strong> This link will expire in 1 hour.
            </p>
            <p style="color: #888; font-size: 13px;">
                If you didn't request a password reset, you can safely ignore this email.
            </p>
        </div>
    </div>
    
    <div style="text-align: center; padding: 20px; color: #888; font-size: 12px;">
        <p style="margin: 0;">&copy; 2026 Resume AI. All rights reserved.</p>
    </div>
</body>
</html>
"""
        
        return self.send_email(to_email, subject, plain_text, html_content)


# Singleton instance
email_service = EmailService()
