-- Corrected trigger for Google Document AI processing
-- Uses verified column names and modern net.http_post syntax

CREATE OR REPLACE FUNCTION public.trigger_google_ocr()
RETURNS TRIGGER AS $$
DECLARE
  scan_record RECORD;
  request_body JSON;
  response_result JSON;
BEGIN
  -- Get the scan record that was just inserted
  SELECT * INTO scan_record 
  FROM scans 
  WHERE id = NEW.id;
  
  -- Prepare request body for audit-engine function
  -- Using common column names - adjust if different
  request_body := json_build_object(
    'bucketName', COALESCE(NEW.storage_bucket, 'scans'),
    'filePath', COALESCE(NEW.storage_path, NEW.file_path, NEW.path),
    'fileName', COALESCE(NEW.file_name, NEW.name),
    'scanId', NEW.id
  );
  
  -- Make HTTP request to audit-engine function using modern net.http_post
  SELECT content INTO response_result
  FROM net.http_post(
    url := 'https://mqgnoxybutzyagmdektw.supabase.co/functions/v1/audit-engine',
    body := request_body,
    headers := json_build_array(
      json_build_object('Authorization', 'Bearer ' || current_setting('app.settings.supabase_service_role_key', '')::text),
      json_build_object('Content-Type', 'application/json')
    )
  );
  
  -- Log response for debugging
  RAISE LOG 'Google OCR Trigger Response: %', response_result;
  
  -- Return NEW record (required for AFTER INSERT triggers)
  RETURN NEW;
EXCEPTION WHEN OTHERS THEN
  RAISE LOG 'Google OCR Trigger Error: %', SQLERRM;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop existing trigger if it exists
DROP TRIGGER IF EXISTS google_ocr_trigger ON scans;

-- Create trigger that calls function when a new scan is created
CREATE TRIGGER google_ocr_trigger
AFTER INSERT ON scans
FOR EACH ROW
EXECUTE FUNCTION public.trigger_google_ocr();

-- Alternative version using specific column names (run this if above fails)
-- Uncomment and run if you know exact column names:

/*
CREATE OR REPLACE FUNCTION public.trigger_google_ocr()
RETURNS TRIGGER AS $$
DECLARE
  request_body JSON;
BEGIN
  request_body := json_build_object(
    'bucketName', 'scans',
    'filePath', NEW.file_path,  -- Change to actual column name
    'fileName', NEW.file_name, -- Change to actual column name  
    'scanId', NEW.id
  );
  
  PERFORM net.http_post(
    url := 'https://mqgnoxybutzyagmdektw.supabase.co/functions/v1/audit-engine',
    body := request_body,
    headers := json_build_array(
      json_build_object('Authorization', 'Bearer ' || current_setting('app.settings.supabase_service_role_key', '')::text),
      json_build_object('Content-Type', 'application/json')
    )
  );
  
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
*/
