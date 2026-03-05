-- Create or replace trigger for Google Document AI processing
-- This trigger will be called when a new scan is created
-- It will automatically call the audit-engine function with the correct parameters

CREATE OR REPLACE FUNCTION public.trigger_google_ocr()
RETURNS TRIGGER AS $$
DECLARE
  scan_record RECORD;
  request_body JSON;
  response_text TEXT;
BEGIN
  -- Get the scan record that was just inserted
  SELECT * INTO scan_record 
  FROM scans 
  WHERE id = NEW.id;
  
  -- Prepare the request body for audit-engine function
  request_body := json_build_object(
    'bucketName', scan_record.storage_bucket,
    'filePath', scan_record.storage_path,
    'fileName', scan_record.file_name,
    'scanId', scan_record.id
  );
  
  -- Make HTTP request to audit-engine function
  SELECT content INTO response_text
  FROM http_post(
    'https://mqgnoxybutzyagmdektw.supabase.co/functions/v1/audit-engine',
    request_body,
    'application/json',
    ARRAY[
      ('Authorization', 'Bearer ' || current_setting('app.settings.supabase_service_role_key', '')::text),
      ('Content-Type', 'application/json')
    ]
  );
  
  -- Log the response for debugging
  RAISE LOG 'Google OCR Trigger Response: %', response_text;
  
  -- Return the NEW record (this is required for AFTER INSERT triggers)
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger that calls the function when a new scan is created
DROP TRIGGER IF EXISTS google_ocr_trigger;

CREATE TRIGGER google_ocr_trigger
AFTER INSERT ON scans
FOR EACH ROW
EXECUTE FUNCTION public.trigger_google_ocr();

-- Helper function for HTTP POST requests (if not already exists)
CREATE OR REPLACE FUNCTION http_post(
  url TEXT,
  body JSON,
  content_type TEXT DEFAULT 'application/json',
  headers JSON DEFAULT '[]'::json
)
RETURNS TEXT AS $$
DECLARE
  result TEXT;
BEGIN
  -- Use pg_net extension for HTTP requests
  SELECT content INTO result
  FROM http_post(
    url := url,
    headers := headers,
    body := body::text,
    content_type := content_type
  );
  
  RETURN result;
EXCEPTION WHEN OTHERS THEN
  RETURN 'Error: ' || SQLERRM;
END;
$$ LANGUAGE plpgsql;
