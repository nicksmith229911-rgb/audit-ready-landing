-- Create audit_results table for Google Document AI processing results
CREATE TABLE IF NOT EXISTS audit_results (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  scan_id UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  file_name TEXT NOT NULL,
  extracted_text TEXT NOT NULL,
  processing_method TEXT NOT NULL DEFAULT 'google_document_ai',
  processed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  metadata JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_audit_results_scan_id ON audit_results(scan_id);
CREATE INDEX IF NOT EXISTS idx_audit_results_processed_at ON audit_results(processed_at);
CREATE INDEX IF NOT EXISTS idx_audit_results_processing_method ON audit_results(processing_method);

-- Create updated_at trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_audit_results_updated_at 
    BEFORE UPDATE ON audit_results 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Add RLS policies
ALTER TABLE audit_results ENABLE ROW LEVEL SECURITY;

-- Policy: Users can view audit results for their own scans
CREATE POLICY "Users can view own audit results" ON audit_results
    FOR SELECT USING (
        auth.uid() IN (
            SELECT user_id FROM scans WHERE id = scan_id
        )
    );

-- Policy: Users can insert audit results for their own scans
CREATE POLICY "Users can insert own audit results" ON audit_results
    FOR INSERT WITH CHECK (
        auth.uid() IN (
            SELECT user_id FROM scans WHERE id = scan_id
        )
    );

-- Policy: Users can update audit results for their own scans
CREATE POLICY "Users can update own audit results" ON audit_results
    FOR UPDATE USING (
        auth.uid() IN (
            SELECT user_id FROM scans WHERE id = scan_id
        )
    );
