-- SQL Script to DELETE old trigger and CREATE new one pointing ONLY to audit-engine
-- Run this in Supabase SQL Editor

-- Step 1: Delete the old trigger if it exists
DROP TRIGGER IF EXISTS google_ocr_trigger ON scans;

-- Step 2: Delete the old trigger function if it exists
DROP FUNCTION IF EXISTS public.trigger_google_ocr();

-- Step 3: Create NEW trigger function that points ONLY to audit-engine
CREATE OR REPLACE FUNCTION public.trigger_google_ocr()
RETURNS TRIGGER
SECURITY DEFINER
LANGUAGE plpgsql
AS $$
DECLARE
  request_body JSON;
  response_result JSON;
  clean_file_path TEXT;
BEGIN
  -- Clean the file_url by removing local:// prefix
  clean_file_path := REPLACE(NEW.file_url, 'local://', '');
  
  -- Prepare request body for audit-engine function
  request_body := json_build_object(
    'bucketName', 'scans',
    'filePath', clean_file_path,
    'fileName', COALESCE(NEW.file_name, split_part(clean_file_path, '/', 2)),
    'scanId', NEW.id
  );
  
  -- Make HTTP request to audit-engine function using net.http_post
  SELECT content INTO response_result
  FROM net.http_post(
    url := 'https://mqgnoxybutzyagmdektw.supabase.co/functions/v1/audit-engine',
    body := request_body,
    headers := json_build_array(
      json_build_object('Authorization', 'Bearer ' || current_setting('app.settings.supabase_service_role_key', '')::text),
      json_build_object('Content-Type', 'application/json')
    )
  );
  
  -- Log the cleaned path and response for debugging
  RAISE LOG 'Google OCR Trigger - Original file_url: %, Cleaned filePath: %, Response: %', 
    NEW.file_url, clean_file_path, response_result;
  
  -- Return NEW record (required for AFTER INSERT triggers)
  RETURN NEW;
EXCEPTION WHEN OTHERS THEN
  RAISE LOG 'Google OCR Trigger Error: %', SQLERRM;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Step 4: Create NEW trigger that calls the function when a new scan is created
CREATE TRIGGER google_ocr_trigger
AFTER INSERT ON scans
FOR EACH ROW
EXECUTE FUNCTION public.trigger_google_ocr();

-- Step 5: Verify the trigger was created
SELECT 
    trigger_name,
    event_manipulation,
    event_object_table,
    action_timing,
    action_orientation
FROM information_schema.triggers 
WHERE trigger_name = 'google_ocr_trigger';

-- Step 6: Verify the function was created
SELECT 
    routine_name,
    routine_type,
    data_type
FROM information_schema.routines 
WHERE routine_name = 'trigger_google_ocr';

-- Success message
SELECT '✅ SUCCESS: Old trigger deleted and new trigger created pointing ONLY to audit-engine' AS status;
