import { useState, useCallback, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Upload, FileCheck, Shield, X, CheckCircle2, Download, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { generateCertificate } from "@/lib/certificate";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/contexts/AuthContext";

interface ScanRecord {
  id: string;
  file_name: string;
  status: string | null;
  compliance_score: number | null;
  created_at: string;
}

const extractTextFromFile = async (file: File): Promise<string> => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.readAsText(file);
  });
};

type ScanStage = "uploading" | "analyzing" | "saving" | null;

const STAGE_LABELS: Record<NonNullable<ScanStage>, string> = {
  uploading: "Uploading…",
  analyzing: "Analyzing…",
  saving: "Saving results…",
};

const SCAN_TIMEOUT_MS = 120_000; // 2 minutes
const MAX_FILE_SIZE_MB = 10; // 10MB file size limit
const SUPPORTED_FILE_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
  "text/csv",
  "text/markdown"
];

const validateFile = (file: File): string | null => {
  // Check file size
  if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
    return `File size exceeds ${MAX_FILE_SIZE_MB}MB limit`;
  }
  
  // Check file type
  if (!SUPPORTED_FILE_TYPES.includes(file.type)) {
    return `Unsupported file type: ${file.type}. Supported types: PDF, Word documents, and text files`;
  }
  
  return null;
};

const Dashboard = () => {
  const { user } = useAuth();
  const [isDragging, setIsDragging] = useState(false);
  const [scanProgress, setScanProgress] = useState(0);
  const [isScanning, setIsScanning] = useState(false);
  const [scanStage, setScanStage] = useState<ScanStage>(null);
  const [currentFileName, setCurrentFileName] = useState("");
  const [scans, setScans] = useState<ScanRecord[]>([]);
  const [activeScanId, setActiveScanId] = useState<string | null>(null);
  const [abortController, setAbortController] = useState<AbortController | null>(null);

  const resetScanState = useCallback(() => {
    setIsScanning(false);
    setScanProgress(0);
    setScanStage(null);
    setCurrentFileName("");
    setActiveScanId(null);
    setAbortController(null);
  }, []);

  // Load existing scans on mount
  useEffect(() => {
    const loadScans = async () => {
      const { data } = await supabase
        .from("scans")
        .select("id, file_name, status, compliance_score, created_at")
        .order("created_at", { ascending: false });
      if (data) setScans(data);
    };
    loadScans();
  }, []);

  const handleCancel = useCallback(() => {
    abortController?.abort();
    // Mark pending record as failed if we have one
    if (activeScanId) {
      supabase
        .from("scans")
        .update({ status: "cancelled" })
        .eq("id", activeScanId)
        .then(() => {
          setScans((prev) =>
            prev.map((s) => (s.id === activeScanId ? { ...s, status: "cancelled" } : s))
          );
        });
    }
    resetScanState();
    toast.info("Scan cancelled");
  }, [abortController, activeScanId, resetScanState]);

  const runScan = useCallback(async (file: File) => {
    if (!user?.id) {
      toast.error("Please sign in to save your results");
      return;
    }

    // Validate file before processing
    const validationError = validateFile(file);
    if (validationError) {
      toast.error(validationError);
      return;
    }

    const controller = new AbortController();
    setAbortController(controller);
    setIsScanning(true);
    setScanStage("uploading");
    setScanProgress(10);
    setCurrentFileName(file.name);

    // Timeout guard
    const timeout = setTimeout(() => {
      controller.abort();
      resetScanState();
      toast.error("Scan timed out", { description: "The analysis took too long. Please try a smaller file." });
    }, SCAN_TIMEOUT_MS);

    let scanRecordId: string | null = null;
    try {
      // 1 — Insert a pending record
      setScanProgress(15);
      const { data: inserted, error: insertErr } = await supabase
        .from("scans")
        .insert({
          file_name: file.name,
          file_url: `local://${file.name}`,
          user_id: user.id,
          status: "pending",
        })
        .select("id, file_name, status, compliance_score, created_at")
        .single();

      if (insertErr || !inserted) {
        throw new Error(insertErr?.message || "Failed to create scan record");
      }

      if (controller.signal.aborted) return;

      scanRecordId = inserted.id;
      setActiveScanId(inserted.id);
      setScans((prev) => [inserted, ...prev]);

      // 2 — Skip text extraction (backend will handle it)
      setScanStage("analyzing");
      setScanProgress(25);

      if (controller.signal.aborted) return;
      setScanProgress(40);

      // 3 — Call AI analysis
      const analyzeUrl = `${import.meta.env.VITE_SUPABASE_URL}/functions/v1/analyze-document`;
      
      // Create FormData to send the file
      const formData = new FormData();
      formData.append("file", file);
      
      const resp = await fetch(analyzeUrl, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY}`,
        },
        body: formData,
        signal: controller.signal,
      });

      setScanProgress(75);

      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.error || `Analysis failed (${resp.status})`);
      }

      let result;
      try {
        result = await resp.json();
        console.log("Raw AI Response:", result); // Debug raw response
      } catch (parseError) {
        console.error("Failed to parse AI response:", parseError);
        throw new Error("Invalid response from AI analysis");
      }

      const score: number = result.score ?? 50;
      const findings: string[] = result.findings ?? [];
      const evidence: string[] = result.evidence ?? []; // Safe array parsing

      console.log("Parsed AI Analysis Result:", { score, findings, evidence }); // Debug log

      if (controller.signal.aborted) return;

      // 4 — Save results
      setScanStage("saving");
      setScanProgress(90);

      const isSafe = score >= 70;
      
      // Try to save to database, but don't fail if it errors
      try {
        const { error: updateErr } = await supabase
          .from("scans")
          .update({
            compliance_score: score,
            status: "completed",
            is_safe: isSafe,
            audit_log: { findings },
            evidence: evidence, // Save to dedicated evidence column
          })
          .eq("id", inserted.id);

        if (updateErr) {
          console.error("Database save error:", updateErr);
          // Continue anyway - AI result is still returned to UI
        }
      } catch (dbError) {
        console.error("Database save failed:", dbError);
        // Continue anyway - AI result is still returned to UI
      }

      setScanProgress(100);
      setScans((prev) =>
        prev.map((s) =>
          s.id === inserted.id ? { ...s, compliance_score: score, status: "completed" } : s
        )
      );
      const isCompliant = score >= 70;
      const complianceStatus = isCompliant ? "COMPLIANT" : "NON-COMPLIANT";
      
      toast[isCompliant ? "success" : "error"](
        `${file.name} — ${complianceStatus}`,
        { description: `Score: ${score}/100 · ${findings.length} finding(s)` }
      );
    } catch (err: unknown) {
      if ((err as Error)?.name === "AbortError") return; // cancelled by user
      const msg = err instanceof Error ? err.message : "Scan failed";
      toast.error(msg);
      // Mark the DB record as failed — use local scanRecordId since activeScanId may not be set yet
      const failId = scanRecordId;
      if (failId) {
        supabase.from("scans").update({ status: "failed" }).eq("id", failId);
        setScans((prev) =>
          prev.map((s) => (s.id === failId ? { ...s, status: "failed" } : s))
        );
      }
    } finally {
      clearTimeout(timeout);
      resetScanState();
    }
  }, [user, resetScanState]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      
      try {
        const file = e.dataTransfer.files[0];
        if (!file) {
          toast.error("No file dropped");
          return;
        }
        
        if (isScanning) {
          toast.error("Please wait for the current scan to complete");
          return;
        }
        
        runScan(file);
      } catch (error) {
        console.error("Drop error:", error);
        toast.error("Failed to process dropped file");
      }
    },
    [runScan, isScanning]
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      try {
        const file = e.target.files?.[0];
        
        if (!file) {
          toast.error("No file selected");
          return;
        }
        
        if (isScanning) {
          toast.error("Please wait for the current scan to complete");
          return;
        }
        
        runScan(file);
      } catch (error) {
        console.error("File input error:", error);
        toast.error("Failed to process selected file");
      } finally {
        e.target.value = "";
      }
    },
    [runScan, isScanning]
  );

  const completedScans = scans.filter((s) => s.status === "completed");
  const compliantScans = completedScans.filter((s) => (s.compliance_score ?? 0) >= 70);
  const nonCompliantScans = completedScans.filter((s) => (s.compliance_score ?? 0) < 70);
  const issueScans = scans.filter((s) => s.status !== "completed" && s.status !== "pending");

  return (
    <div className="space-y-8">
      {/* Stats row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[
          { label: "Files Scanned", value: scans.length, icon: FileCheck },
          { label: "Compliant", value: compliantScans.length, icon: Shield },
          { label: "Non-Compliant", value: nonCompliantScans.length, icon: X },
          { label: "Issues Found", value: issueScans.length, icon: X },
        ].map((stat) => (
          <Card key={stat.label} className="border-border/50 bg-card/80 backdrop-blur">
            <CardContent className="flex items-center gap-4 p-5">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                <stat.icon className="h-5 w-5 text-primary" />
              </div>
              <div>
                <p className="text-2xl font-bold">{stat.value}</p>
                <p className="text-xs text-muted-foreground">{stat.label}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Upload area */}
      <Card className="border-border/50 bg-card/80 backdrop-blur">
        <CardHeader>
          <CardTitle className="text-lg">Upload Documents</CardTitle>
          <CardDescription>Drag & drop PDF, Word, or text files to scan for AI compliance issues (Max 10MB)</CardDescription>
        </CardHeader>
        <CardContent>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-12 transition-all ${
              isDragging
                ? "border-primary bg-primary/5"
                : "border-border hover:border-primary/50 hover:bg-primary/5"
            }`}
          >
            <Upload
              className={`mb-4 h-10 w-10 ${isDragging ? "text-primary" : "text-muted-foreground"}`}
            />
            <p className="mb-1 text-sm font-medium">
              {isDragging ? "Drop file here" : "Drag & drop your file here"}
            </p>
            <p className="mb-4 text-xs text-muted-foreground">or</p>
            <label>
              <Button variant="outline" size="sm" asChild>
                <span>Browse Files</span>
              </Button>
              <input
                type="file"
                className="sr-only"
                onChange={handleFileInput}
                disabled={isScanning}
                accept=".pdf,.docx,.txt,.csv,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/csv,text/markdown"
              />
            </label>
          </div>

          {/* Progress bar */}
          {isScanning && (
            <div className="mt-6 space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin text-primary" />
                  {scanStage ? STAGE_LABELS[scanStage] : "Starting…"}{" "}
                  <span className="font-medium text-foreground">{currentFileName}</span>
                </span>
                <span className="font-mono text-primary">
                  {Math.min(Math.round(scanProgress), 100)}%
                </span>
              </div>
              <Progress value={Math.min(scanProgress, 100)} className="h-2" />
              <div className="flex justify-end">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 gap-1.5 text-xs text-destructive hover:text-destructive"
                  onClick={handleCancel}
                >
                  <X className="h-3.5 w-3.5" />
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Scan results */}
      {scans.length > 0 && (
        <Card className="border-border/50 bg-card/80 backdrop-blur">
          <CardHeader>
            <CardTitle className="text-lg">Scan Results</CardTitle>
            <CardDescription>
              {completedScans.length}/{scans.length} files compliant
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {scans.map((scan) => (
                <div
                  key={scan.id}
                  className="flex items-center justify-between rounded-lg border border-border/50 bg-background/50 p-3"
                >
                  <div className="flex items-center gap-3">
                    <FileCheck className="h-4 w-4 text-muted-foreground" />
                    <div>
                      <p className="text-sm font-medium">{scan.file_name}</p>
                      <p className="text-xs text-muted-foreground">
                        {scan.status === "completed"
                          ? `Score: ${scan.compliance_score}/100`
                          : "Pending…"}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span
                      className={`flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${
                        scan.status === "completed"
                          ? (scan.compliance_score ?? 0) >= 70
                            ? "bg-primary/10 text-primary"
                            : "bg-red-10 text-red-600"
                          : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {scan.status === "completed" ? (
                        (scan.compliance_score ?? 0) >= 70 ? (
                          <CheckCircle2 className="h-3 w-3" />
                        ) : (
                          <X className="h-3 w-3" />
                        )
                      ) : (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      )}
                      {scan.status === "completed"
                        ? (scan.compliance_score ?? 0) >= 70
                          ? "COMPLIANT"
                          : "NON-COMPLIANT"
                        : "Pending"}
                    </span>

                    {scan.status === "completed" && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 gap-1.5 text-xs text-primary hover:text-primary"
                        onClick={() =>
                          generateCertificate({
                            fileName: scan.file_name,
                            score: scan.compliance_score ?? 0,
                            date: scan.created_at,
                            scanId: scan.id,
                          })
                        }
                      >
                        <Download className="h-3.5 w-3.5" />
                        Certificate
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default Dashboard;
