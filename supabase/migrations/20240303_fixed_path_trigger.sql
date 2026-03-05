-- Fixed trigger for Google Document AI processing
-- Cleans file_url to remove local:// prefix before sending to function

CREATE OR REPLACE FUNCTION public.trigger_google_ocr()
RETURNS TRIGGER AS $$
DECLARE
  scan_record RECORD;
  request_body JSON;
  response_result JSON;
  clean_file_path TEXT;
BEGIN
  -- Get the file_url from the new record
  clean_file_path := REPLACE(NEW.file_url, 'local://', '');
  clean_file_path := REPLACE(clean_file_path, 'http://', '');
  clean_file_path := REPLACE(clean_file_path, 'https://', '');
  
  -- Prepare request body for audit-engine function
  request_body := json_build_object(
    'bucketName', COALESCE(NEW.storage_bucket, 'scans'),
    'filePath', clean_file_path,
    'fileName', COALESCE(NEW.file_name, split_part(clean_file_path, '/', 2)),
    'scanId', NEW.id
  );
  
  -- Make HTTP request to audit-engine function
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

-- Drop existing trigger if it exists
DROP TRIGGER IF EXISTS google_ocr_trigger ON scans;

-- Create trigger that calls function when a new scan is created
CREATE TRIGGER google_ocr_trigger
AFTER INSERT ON scans
FOR EACH ROW
EXECUTE FUNCTION public.trigger_google_ocr();
