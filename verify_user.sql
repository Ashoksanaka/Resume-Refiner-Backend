-- SQL command to verify email for user test@gmail.com
UPDATE users 
SET is_verified = true 
WHERE email = 'test@gmail.com';

-- Verify the update
SELECT email, is_verified 
FROM users 
WHERE email = 'test@gmail.com';
