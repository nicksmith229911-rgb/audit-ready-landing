-- Diagnostic query to get exact column names for public.scans table
-- Run this first to see the actual schema

SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns 
WHERE table_schema = 'public' 
  AND table_name = 'scans'
ORDER BY ordinal_position;
