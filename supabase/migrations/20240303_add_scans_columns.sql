-- Migration to add missing columns to scans table
-- Run this in Supabase SQL Editor

-- Step 1: Add storage_bucket column if it doesn't exist
DO $$
BEGIN
    ALTER TABLE scans 
    ADD COLUMN IF NOT EXISTS storage_bucket TEXT;
EXCEPTION
    WHEN duplicate_column THEN
        -- Column already exists, do nothing
        NULL;
END;
$$;

-- Step 2: Add file_url column if it doesn't exist (for safety)
DO $$
BEGIN
    ALTER TABLE scans 
    ADD COLUMN IF NOT EXISTS file_url TEXT;
EXCEPTION
    WHEN duplicate_column THEN
        -- Column already exists, do nothing
        NULL;
END;
$$;

-- Step 3: Verify columns were added successfully
SELECT 
    column_name, 
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'scans' 
    AND column_name IN ('storage_bucket', 'file_url')
ORDER BY column_name;

-- Success message
SELECT '✅ SUCCESS: Added storage_bucket and file_url columns to scans table' AS status;
