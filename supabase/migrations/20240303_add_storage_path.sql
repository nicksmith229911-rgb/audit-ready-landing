-- Migration to add storage_path column to scans table
-- Run this in Supabase SQL Editor

-- Step 1: Add storage_path column if it doesn't exist
DO $$
BEGIN
    ALTER TABLE scans 
    ADD COLUMN IF NOT EXISTS storage_path TEXT;
EXCEPTION
    WHEN duplicate_column THEN
        -- Column already exists, do nothing
        NULL;
END;
$$;

-- Step 2: Verify all required columns exist
SELECT 
    column_name, 
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'scans' 
    AND column_name IN ('storage_bucket', 'storage_path', 'file_url')
ORDER BY column_name;

-- Step 3: Update any existing records that have file_url but no storage_path
UPDATE scans 
SET storage_path = REPLACE(file_url, 'local://', '')
WHERE storage_path IS NULL 
    AND file_url IS NOT NULL 
    AND file_url LIKE 'local://%';

-- Step 4: Show updated records count
SELECT 
    COUNT(*) as updated_records,
    'Records updated with storage_path from file_url' as action
FROM scans 
WHERE storage_path IS NOT NULL 
    AND file_url IS NOT NULL;

-- Success message
SELECT '✅ SUCCESS: Added storage_path column and updated existing records' AS status;
