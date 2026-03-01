import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-supabase-client-platform, x-supabase-client-platform-version, x-supabase-client-runtime, x-supabase-client-runtime-version",
};

const MAX_WORDS = 10000;

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
    const text = new TextDecoder("utf-8", { fatal: false }).decode(bytes);
    
    // Extract readable text from PDF (basic approach)
    // Look for common text patterns in PDFs
    const textPatterns = [
      /BT\s*[\d.]+\s*[\d.]+\s*Td\s*\((.*?)\)\s*Tj/g,
      /\((.*?)\)\s*Tj/g,
      /[\w\s.,;:!?'"()-]+/g
    ];
    
    let extractedText = "";
    for (const pattern of textPatterns) {
      const matches = text.match(pattern);
      if (matches) {
        extractedText += matches.join(" ") + " ";
      }
    }
    
    // Clean up the extracted text
    extractedText = extractedText
      .replace(/\\\(/g, "(")
      .replace(/\\\)/g, ")")
      .replace(/\\n/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    
    return extractedText || "Could not extract text from PDF. The PDF may be scanned or protected.";
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
    
    // Extract text from DOCX XML structure
    const textMatches = text.match(/<w:t[^>]*>(.*?)<\/w:t>/g);
    if (textMatches) {
      const extractedText = textMatches
        .map(match => match.replace(/<[^>]*>/g, ""))
        .join(" ")
        .replace(/\s+/g, " ")
        .trim();
      return extractedText || "Could not extract text from DOCX file.";
    }
    
    return "Could not extract text from DOCX file. The file may be corrupted.";
  } catch (error) {
    console.error("DOCX extraction error:", error);
    return "Failed to extract text from DOCX file. The file may be corrupted or password-protected.";
  }
}

async function analyzeChunk(
  chunk: string,
  fileName: string,
  chunkIndex: number,
  totalChunks: number,
  apiKey: string
): Promise<{ score: number; findings: string[]; evidence: string[] }> {
  const systemPrompt = `You are a STRICT SOC2 and ISO27001 Auditor. Your task is to identify ONLY security controls that are EXPLICITLY mentioned in the provided document text.

CRITICAL RULES:
1. ONLY report security controls that are explicitly stated in the text
2. For each finding, you MUST provide the exact quote evidence from the document
3. If you cannot find evidence for a security control, it is a GAP - do not invent it
4. Be extremely skeptical and evidence-based
5. Do not assume or infer security practices that are not written

SCORING GUIDELINES:
- 80-100: Document explicitly mentions most required controls with clear evidence
- 60-79: Document mentions some controls but has clear gaps
- 40-59: Document mentions few controls and has significant gaps  
- 0-39: Document mentions almost no security controls

EVIDENCE REQUIREMENTS:
- Each finding must have a direct quote from the document
- Evidence must be verbatim text, not paraphrased
- If no evidence exists for a control, do not report it

Return ONLY valid JSON with this exact format:
{
  "score": 0-100,
  "findings": ["specific finding with evidence"],
  "evidence": ["exact quote from document text"]
}

Example response:
{
  "score": 35,
  "findings": ["No MFA configuration mentioned"],
  "evidence": ["The document discusses user authentication but does not mention multi-factor authentication"]
}`;

  const chunkLabel = totalChunks > 1 ? ` (chunk ${chunkIndex + 1}/${totalChunks})` : "";

  const response = await fetch("https://ai.gateway.lovable.dev/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "google/gemini-3-flash-preview",
      temperature: 0.1, // Low temperature for consistent, factual responses
      messages: [
        { role: "system", content: systemPrompt },
        {
          role: "user",
          content: `Analyze this document${chunkLabel} for SOC2/ISO27001 compliance. The file is named "${fileName}".\n\nDocument content:\n${chunk}`,
        },
      ],
    }),
  });

  if (!response.ok) {
    const errText = await response.text();
    console.error("AI gateway error:", response.status, errText);
    if (response.status === 429) throw new Error("Rate limit exceeded, please try again later.");
    if (response.status === 402) throw new Error("AI credits exhausted. Please add credits.");
    throw new Error(`AI gateway error: ${response.status}`);
  }

  const data = await response.json();
  const content = data.choices?.[0]?.message?.content ?? "";

  try {
    const cleaned = content.replace(/```json?\s*/g, "").replace(/```/g, "").trim();
    const parsed = JSON.parse(cleaned);
    
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
  } catch {
    console.error("Failed to parse AI response:", content);
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
    const contentType = req.headers.get("content-type") || "";
    let text: string = "";
    let fileName: string = "";

    if (contentType.includes("application/json")) {
      // Handle JSON request (existing format)
      const body = await req.json();
      text = body.text;
      fileName = body.fileName;
    } else if (contentType.includes("multipart/form-data")) {
      // Handle file upload
      const formData = await req.formData();
      const file = formData.get("file") as File;
      fileName = file?.name || "unknown";
      
      if (!file) {
        return new Response(
          JSON.stringify({ error: "No file provided" }),
          { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
        );
      }

      const arrayBuffer = await file.arrayBuffer();
      const mimeType = file.type;

      // Extract text based on file type
      if (mimeType === "application/pdf") {
        text = await extractTextFromPDF(arrayBuffer);
      } else if (mimeType === "application/vnd.openxmlformats-officedocument.wordprocessingml.document") {
        text = await extractTextFromDOCX(arrayBuffer);
      } else if (mimeType.startsWith("text/")) {
        // Handle text files
        text = new TextDecoder().decode(arrayBuffer);
      } else {
        return new Response(
          JSON.stringify({ error: `Unsupported file type: ${mimeType}` }),
          { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
        );
      }
    } else {
      return new Response(
        JSON.stringify({ error: "Unsupported content type" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    if (!text || typeof text !== "string" || text.trim().length === 0) {
      return new Response(
        JSON.stringify({ error: "No document text could be extracted from the file" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    const LOVABLE_API_KEY = Deno.env.get("LOVABLE_API_KEY");
    if (!LOVABLE_API_KEY) throw new Error("LOVABLE_API_KEY is not configured");

    const chunks = splitIntoChunks(text.trim(), MAX_WORDS);
    console.log(`Processing ${chunks.length} chunk(s) for "${fileName}"`);

    const results = [];
    for (const [i, chunk] of chunks.entries()) {
      const result = await analyzeChunk(chunk, fileName, i, chunks.length, LOVABLE_API_KEY);
      results.push(result);
    }

    // Combine: average score, merge unique findings and evidence
    const avgScore = Math.round(results.reduce((sum, r) => sum + r.score, 0) / results.length);
    const allFindings = [...new Set(results.flatMap((r) => r.findings))];
    const allEvidence = [...new Set(results.flatMap((r) => r.evidence || []))];

    return new Response(JSON.stringify({ 
      score: avgScore, 
      findings: allFindings,
      evidence: allEvidence 
    }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  } catch (e) {
    console.error("analyze-document error:", e);
    return new Response(
      JSON.stringify({ error: e instanceof Error ? e.message : "Unknown error" }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
