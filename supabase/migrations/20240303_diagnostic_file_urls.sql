-- Diagnostic query to see file_url format in scans table
-- Run this to understand the current file_url format

SELECT 
    id,
    file_url,
    file_name,
    storage_path,
    storage_bucket,
    created_at
FROM public.scans 
LIMIT 5;
