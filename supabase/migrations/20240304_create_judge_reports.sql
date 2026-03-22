-- Migration: Create judge_reports table for the Judge's 6-part Constitution deliverable
-- This table stores the final consensus output from Gemini 3.1 Pro (the Judge)
-- after it synthesizes all 3 Jury reports into a single authoritative verdict.

-- 1. Create the judge_reports table (6-part Constitution Schema)
CREATE TABLE IF NOT EXISTS judge_reports (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    scan_id UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    executive_summary TEXT,
    consensus_scorecard JSONB,
    critical_risks_heatmap JSONB,
    areas_for_improvement JSONB,
    maturity_rating TEXT,
    appendices JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Create indexes for query performance
CREATE INDEX IF NOT EXISTS idx_judge_reports_scan_id ON judge_reports(scan_id);

-- 3. Create updated_at trigger (reuses the function from audit_results migration)
CREATE TRIGGER update_judge_reports_updated_at
    BEFORE UPDATE ON judge_reports
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 4. Enable Row Level Security (RLS)
ALTER TABLE judge_reports ENABLE ROW LEVEL SECURITY;

-- 5. RLS Policies (mirrors audit_results pattern — user-isolation)
CREATE POLICY "Users can view own judge reports" ON judge_reports
    FOR SELECT USING (
        auth.uid() = user_id
    );

CREATE POLICY "Users can insert own judge reports" ON judge_reports
    FOR INSERT WITH CHECK (
        auth.uid() = user_id
    );

CREATE POLICY "Users can update own judge reports" ON judge_reports
    FOR UPDATE USING (
        auth.uid() = user_id
    );
