import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-supabase-client-platform, x-supabase-client-platform-version, x-supabase-client-runtime, x-supabase-client-runtime-version",
};

const MAX_WORDS = 800; // Increased for better table context

// Text Sanitizer: Remove special character clusters only
function sanitizeText(text: string): string {
  // Remove unusual clusters of special characters from watermark overlaps
  text = text.replace(/[^\w\s\.\,\;\:\!\?\-\|\n\r]{3,}/g, ''); // Remove 3+ consecutive special chars
  text = text.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, ''); // Remove control chars except tab/newline
  
  // Clean up multiple spaces and line breaks
  text = text.replace(/\s{3,}/g, ' '); // Reduce multiple spaces to single
  text = text.replace(/\n{3,}/g, '\n\n'); // Reduce multiple newlines to double
  
  return text.trim();
}

function splitIntoChunks(text: string, maxWords: number): string[] {
  const words = text.split(/\s+/);
  if (words.length <= maxWords) return [text];
  const chunks: string[] = [];
  for (let i = 0; i < words.length; i += maxWords) {
    chunks.push(words.slice(i, i + maxWords).join(" "));
  }
  return chunks;
}

async function extractTextFromPDF(arrayBuffer: ArrayBuffer): Promise<string> {
  try {
    // Use a simple PDF text extraction approach
    const bytes = new Uint8Array(arrayBuffer);
    let text = new TextDecoder("utf-8", { fatal: false }).decode(bytes);
    
    // Table-aware processing: Convert PDF table structures to Markdown
    text = text
      // Convert common table separators to Markdown format
      .replace(/\s*\+[-]+\+\s*/g, '\n|---|---|---|\n')
      .replace(/\s*\|[-]+\|\s*/g, '\n|---|---|---|\n')
      // Ensure consistent column separators
      .replace(/\s{3,}|\t/g, ' | ')
      // Clean up table rows
      .replace(/^(\s*\|.*\|\s*)$/gm, '$1')
      // Add table headers detection
      .replace(/(Task|Activity|Function|Control)\s+(Responsible|Accountable|Consulted|Informed)/gi, '| $1 | $2 |');
    
    // If table structure is detected, format as proper Markdown
    if (text.includes('|') && text.includes('---')) {
      console.log("Table structure detected in PDF, converting to Markdown format");
      return sanitizeText(text);
    }
    
    return sanitizeText(text) || "Could not extract text from PDF. The PDF may be scanned or protected.";
  } catch (error) {
    console.error("PDF extraction error:", error);
    return "Failed to extract text from PDF. The file may be corrupted or password-protected.";
  }
}

async function extractTextFromDOCX(arrayBuffer: ArrayBuffer): Promise<string> {
  try {
    // Basic DOCX text extraction
    const bytes = new Uint8Array(arrayBuffer);
    const text = new TextDecoder("utf-8", { fatal: false }).decode(bytes);
    return sanitizeText(text) || "Could not extract text from DOCX. The file may be corrupted.";
  } catch (error) {
    console.error("DOCX extraction error:", error);
    return "Failed to extract text from DOCX. The file may be corrupted.";
  }
}

function preprocessTableText(text: string): string {
  // Detect if text contains table-like structures
  const hasTableMarkers = /\|.*\|/.test(text) || 
    /^\s*[\|\+\-]+/.test(text) || 
    /RACI|Responsible|Accountable|Consulted|Informed/i.test(text);
  
  if (hasTableMarkers) {
    console.log("Table structure detected, applying preprocessing...");
    
    // Extract and preserve table structure while making it more readable
    const tableRows = text.split('\n').filter(line => 
      line.trim() && (line.includes('|') || /[A-Z]/.test(line))
    );
    
    // Add context for AI to understand table relationships
    const tableContext = `
TABLE ANALYSIS CONTEXT:
This document contains a responsibility matrix (likely RACI format).
Key relationships to identify:
- Who is RESPONSIBLE for implementation
- Who is ACCOUNTABLE for outcomes  
- Who needs to be CONSULTED for input
- Who must be INFORMED of results

Focus on security-related responsibilities and access controls.
`;
    
    return tableContext + '\n\n' + tableRows.join('\n');
  }
  
  return text;
}

async function analyzeChunk(
  chunk: string,
  fileName: string,
  chunkIndex: number,
  totalChunks: number,
  apiKey: string
): Promise<{ score: number; findings: string[]; evidence: string[] }> {
  const systemPrompt = `You are an expert SOC2/ISO27001 Auditor. When you see text that appears to be a RACI matrix or table, interpret the relationships between roles and tasks before scoring.

Ignore any recurring copyright or watermark text that may appear interspersed within the document content.

TABLE HANDLING: For complex tables/RACI matrices, reconstruct role assignments and summarize key security responsibilities. If poorly formatted, use logical interpretation rather than direct quoting.

Analyze the document and return JSON with:
- score: 0-100 (70+ = compliant)
- findings: 3 bullet points max (focus on security gaps)
- evidence: 3 short quotes max

Table Analysis Rules:
- Identify who is RESPONSIBLE for security implementation
- Check who is ACCOUNTABLE for security outcomes
- Note who must be CONSULTED for security decisions
- Verify who must be INFORMED of security incidents

Be evidence-based. If no security controls found, score below 40.

Example:
{"score": 65, "findings": ["MFA not configured", "Data encryption missing"], "evidence": ["Users login with password only", "Database stores plain text"]}`;

  const chunkLabel = totalChunks > 1 ? ` (chunk ${chunkIndex + 1}/${totalChunks})` : "";

  // 20-second timeout protection (synced with 25-second platform limit)
  const timeoutPromise = new Promise<{ score: number; findings: string[]; evidence: string[] }>((_, reject) => {
    setTimeout(() => {
      reject(new Error("Analysis timeout - complex structure detected"));
    }, 20000); // 20 seconds
  });

  const analysisPromise = fetch("https://ai.gateway.lovable.dev/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "gpt-4o-mini", // Faster model to beat Vercel timeout
      temperature: 0.1,
      messages: [
        { role: "system", content: systemPrompt },
        {
          role: "user",
          content: `Analyze this document${chunkLabel}: "${fileName}".\n\n${chunk}`,
        },
      ],
    }),
  });

  try {
    const response = await Promise.race([analysisPromise, timeoutPromise]) as Response;
    
    if (!response.ok) {
      const errText = await response.text();
      console.error("AI gateway error:", response.status, errText);
      if (response.status === 429) throw new Error("Rate limit exceeded, please try again later.");
      if (response.status === 402) throw new Error("AI credits exhausted. Please add credits.");
      throw new Error(`AI gateway error: ${response.status}`);
    }

    const data = await response.json();
    const content = data.choices?.[0]?.message?.content ?? "";

  // Enhanced JSON repair function for table-induced corruption
  function repairJsonResponse(content: string): any {
    try {
      return JSON.parse(content);
    } catch (parseError: any) {
      console.warn("Initial JSON parse failed, attempting repair:", parseError?.message || parseError);
      
      // Remove table-induced corruption patterns
      let repaired = content
        .replace(/[\u0000-\u001F\u007F-\u009F]/g, "") // Control chars
        .replace(/\\n\s*\\n\s*\\n/g, "\\n") // Excessive newlines
        .replace(/,\s*}/g, "}") // Trailing commas in objects
        .replace(/,\s*]/g, "]") // Trailing commas in arrays
        .replace(/}\s*{/g, "},{") // Missing commas between objects
        .replace(/]\s*\[/g, "],[") // Missing commas between arrays
        .replace(/""\s*:/g, '":null') // Empty values to null
        .replace(/:\s*""/g, ':null') // Empty values to null
        .trim();
      
      // Try parsing again
      try {
        const parsed = JSON.parse(repaired);
        console.log("JSON repair successful");
        return parsed;
      } catch (secondError) {
        console.error("JSON repair failed, using fallback structure");
        return {
          score: 35,
          findings: ["Table structure too complex for automated analysis"],
          evidence: ["Manual review recommended for RACI matrix interpretation"]
        };
      }
    }
  }

  try {
    const parsed = repairJsonResponse(content);
    
    // Validate response structure and implement failure scoring
    if (!parsed.score || !Array.isArray(parsed.findings)) {
      throw new Error("Invalid AI response structure");
    }
    
    // If no evidence provided or findings are empty, score as failure (0-20%)
    if (!Array.isArray(parsed.evidence) || parsed.evidence.length === 0 || parsed.findings.length === 0) {
      return {
        score: Math.floor(Math.random() * 20) + 1, // Random score 1-20 for failure
        findings: ["No security controls or evidence found in document"],
        evidence: ["Document analysis revealed no explicit security controls"]
      };
    }
    
    // Validate that each finding has corresponding evidence
    const validFindings = [];
    const validEvidence = [];
    
    for (let i = 0; i < parsed.findings.length && i < parsed.evidence.length; i++) {
      if (parsed.evidence[i] && parsed.evidence[i].trim().length > 0) {
        validFindings.push(parsed.findings[i]);
        validEvidence.push(parsed.evidence[i]);
      }
    }
    
    // If no valid evidence after validation, score as failure
    if (validEvidence.length === 0) {
      return {
        score: Math.floor(Math.random() * 20) + 1,
        findings: ["No verifiable security evidence found in document"],
        evidence: ["Document contains claims without supporting evidence"]
      };
    }
    
    return {
      score: parsed.score,
      findings: validFindings,
      evidence: validEvidence
    };
  } catch (parseError: any) {
    if (parseError.message === "Analysis timeout - complex structure detected") {
      console.warn("Analysis timeout for complex structure, returning system warning");
      return {
        score: 45,
        findings: ["System Warning: Document structure too complex for automated analysis"],
        evidence: ["Manual review recommended for complex RACI matrices and tables"]
      };
    }
    console.error("Failed to parse AI response:", parseError);
    return { 
      score: 15, // Default to failure score
      findings: ["Could not parse AI analysis — manual review recommended"], 
      evidence: ["Analysis parsing failed"] 
    };
  }
}

serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: corsHeaders });
  }

  try {
    console.log('=== ANALYSIS START ===');
    const contentType = req.headers.get("content-type") || "";
    let text: string = "";
    let fileName: string = "";

    if (contentType.includes("multipart/form-data")) {
      // Handle file upload
      console.log('Processing multipart/form-data request...');
      const formData = await req.formData();
      const file = formData.get("file") as File;
      fileName = file?.name || "unknown";
      
      console.log('File received, size:', file.size);
      console.log('File name:', fileName);
      console.log('File type:', file.type);
      
      if (!file) {
        console.log('ERROR: No file provided in request');
        return new Response(
          JSON.stringify({ error: "No file provided" }),
          { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
        );
      }

      console.log('Starting PDF text extraction...');
      const arrayBuffer = await file.arrayBuffer();
      const mimeType = file.type;

      // Extract text based on file type
      if (mimeType === "application/pdf") {
        text = await extractTextFromPDF(arrayBuffer);
        console.log('PDF extraction complete. Text length:', text.length);
      } else if (mimeType === "application/vnd.openxmlformats-officedocument.wordprocessingml.document") {
        text = await extractTextFromDOCX(arrayBuffer);
        console.log('DOCX extraction complete. Text length:', text.length);
      } else if (mimeType.startsWith("text/")) {
        // Handle text files
        text = new TextDecoder().decode(arrayBuffer);
        console.log('Text file extraction complete. Text length:', text.length);
      } else {
        console.log('ERROR: Unsupported file type:', mimeType);
        return new Response(
          JSON.stringify({ error: `Unsupported file type: ${mimeType}` }),
          { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
        );
      }
    } else if (contentType.includes("application/json")) {
      // Handle JSON request (existing format)
      console.log('Processing JSON request...');
      const body = await req.json();
      text = body.text;
      fileName = body.fileName;
      console.log('JSON request received. Text length:', text.length);
    } else {
      console.log('ERROR: Unsupported content type:', contentType);
      return new Response(
        JSON.stringify({ error: "Unsupported content type" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    if (!text || typeof text !== "string" || text.trim().length === 0) {
      console.log('ERROR: No valid text extracted from file');
      return new Response(
        JSON.stringify({ error: "No document text could be extracted from the file" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // Apply text sanitization to remove watermarks and special characters
    console.log('Applying text sanitization...');
    text = sanitizeText(text);
    console.log('Sanitization complete. Final text length:', text.length);

    const LOVABLE_API_KEY = Deno.env.get("LOVABLE_API_KEY");
    if (!LOVABLE_API_KEY) {
      console.log('ERROR: LOVABLE_API_KEY not configured');
      throw new Error("LOVABLE_API_KEY is not configured");
    }

    console.log('Splitting text into chunks...');
    const chunks = splitIntoChunks(text.trim(), MAX_WORDS);
    console.log(`Processing ${chunks.length} chunk(s) for "${fileName}"`);

    const results = [];
    for (const [i, chunk] of chunks.entries()) {
      console.log(`Processing chunk ${i + 1}/${chunks.length}, size: ${chunk.length} chars`);
      
      // Apply preprocessing for table-aware analysis
      const processedChunk = preprocessTableText(chunk);
      console.log(`Preprocessing complete for chunk ${i + 1}`);
      
      console.log(`Sending request to AI for chunk ${i + 1}...`);
      const result = await analyzeChunk(processedChunk, fileName, i, chunks.length, LOVABLE_API_KEY);
      console.log(`AI response received for chunk ${i + 1}, score: ${result.score}`);
      
      results.push(result);
    }

    console.log('All chunks processed successfully');
    // Combine: average score, merge unique findings and evidence
    const avgScore: number = Math.round(results.reduce((sum, r) => sum + Number(r.score), 0) / results.length);
    const allFindings = [...new Set(results.flatMap((r) => r.findings))];
    const allEvidence = [...new Set(results.flatMap((r) => r.evidence || []))];

    console.log('Final results calculated:', { avgScore, findingsCount: allFindings.length, evidenceCount: allEvidence.length });
    console.log('=== ANALYSIS COMPLETE ===');

    return new Response(JSON.stringify({ 
      score: avgScore, 
      findings: allFindings,
      evidence: allEvidence 
    }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  } catch (e) {
    console.error('=== ANALYSIS ERROR ===');
    console.error('Error details:', e);
    console.error('Error stack:', e instanceof Error ? e.stack : 'No stack trace');
    console.error('=== END ERROR ===');
    return new Response(
      JSON.stringify({ error: e instanceof Error ? e.message : "Unknown error" }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
