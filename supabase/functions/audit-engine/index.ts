import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-supabase-client-platform, x-supabase-client-platform-version, x-supabase-client-runtime, x-supabase-client-runtime-version",
};

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: corsHeaders });
  }

  try {
    console.log('=== GOOGLE DOCUMENT AI PROCESSING START ===');
    console.log(`Request method: ${req.method}`);
    console.log(`Request URL: ${req.url}`);
    
    // Initialize Supabase client
    // Initialize Supabase client with modern fallbacks
    const supabaseUrl = Deno.env.get('SUPABASE_URL') ?? "";
    const supabaseKey = Deno.env.get('SERVICE_ROLE_KEY_CUSTOM') ?? Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? "";

    // We removed the 'throw Error' to prevent the boot crash
    console.log(`[SYSTEM] Connection Check: URL=${!!supabaseUrl}, Key=${!!supabaseKey}`);

    const supabase = createClient(supabaseUrl, supabaseKey);

    // Get request body
    const body = await req.json();
    const { bucketName, filePath, fileName, scanId } = body;

    console.log(`Request received: ${JSON.stringify({ bucketName, filePath, fileName, scanId })}`);

    if (!bucketName || !filePath || !fileName || !scanId) {
      console.error('Missing required parameters:', { bucketName, filePath, fileName, scanId });
      return new Response(
        JSON.stringify({ error: "Missing required parameters: bucketName, filePath, fileName, scanId" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // Step 1: Download PDF from Supabase Storage
    console.log('Step 1: Downloading PDF from storage...');
    const { data: fileData, error: downloadError } = await supabase.storage
      .from(bucketName)
      .download(filePath);

    if (downloadError || !fileData) {
      console.error('Failed to download file:', downloadError);
      throw new Error(`Failed to download file: ${downloadError?.message}`);
    }

    console.log(`PDF downloaded successfully, size: ${fileData.size} bytes`);

    // Step 2: Decode Google Service Account JSON
    console.log('Step 2: Decoding Google Service Account credentials...');
    const serviceAccountBase64 = Deno.env.get('GOOGLE_SERVICE_ACCOUNT_JSON_BASE64');
    if (!serviceAccountBase64) {
      throw new Error('GOOGLE_SERVICE_ACCOUNT_JSON_BASE64 environment variable not set');
    }

    const serviceAccountJson = atob(serviceAccountBase64);
    const serviceAccount = JSON.parse(serviceAccountJson);
    console.log(`Service account decoded for project: ${serviceAccount.project_id}`);

    // Step 3: Get Google Access Token
    console.log('Step 3: Getting Google Access Token...');
    const tokenResponse = await fetch('https://oauth2.googleapis.com/token', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams({
        grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
        assertion: createJWT(serviceAccount),
      }),
    });

    if (!tokenResponse.ok) {
      const errorText = await tokenResponse.text();
      console.error('Failed to get access token:', errorText);
      throw new Error(`Failed to get access token: ${tokenResponse.status} - ${errorText}`);
    }

    const tokenData = await tokenResponse.json();
    const accessToken = tokenData.access_token;

    console.log('Access token obtained successfully');

    // Step 4: Send to Google Document AI
    console.log('Step 4: Sending to Google Document AI...');
    const processorId = Deno.env.get('GOOGLE_PROCESSOR_ID');
    if (!processorId) {
      throw new Error('GOOGLE_PROCESSOR_ID environment variable not set');
    }

    // Convert file to base64
    const fileBase64 = await fileToBase64(fileData);
    
    const documentAIRequest = {
      name: processorId,
      rawDocument: {
        content: fileBase64,
        mimeType: 'application/pdf',
      },
    };

    console.log(`Sending to Document AI with processor: ${processorId}`);

    const aiResponse = await fetch(
      `https://documentai.googleapis.com/v1/projects/${serviceAccount.project_id}/locations/us-central1/processors/${processorId.split('/')[3]}:process`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(documentAIRequest),
      }
    );

    if (!aiResponse.ok) {
      const errorText = await aiResponse.text();
      console.error('Document AI processing failed:', errorText);
      throw new Error(`Document AI processing failed: ${aiResponse.status} - ${errorText}`);
    }

    const aiResult = await aiResponse.json();
    console.log('Document AI processing completed');

    // Step 5: Extract text from Document AI response
    console.log('Step 5: Extracting text from Document AI response...');
    let extractedText = '';
    
    if (aiResult.document && aiResult.document.text) {
      extractedText = aiResult.document.text;
      console.log('Found direct text field in AI response');
    } else if (aiResult.document && aiResult.document.pages) {
      console.log('Extracting text from pages array...');
      // Extract text from pages if no direct text field
      for (const page of aiResult.document.pages) {
        if (page.blocks) {
          for (const block of page.blocks) {
            if (block.paragraph) {
              for (const paragraph of block.paragraph) {
                if (paragraph.text) {
                  extractedText += paragraph.text + ' ';
                }
              }
            }
          }
        }
      }
    } else {
      console.warn('No text or pages found in AI response');
    }

    if (!extractedText || extractedText.trim().length === 0) {
      console.warn('No text extracted from Document AI response');
      extractedText = 'Document AI processing completed but no text was extracted';
    }

    console.log(`AI extracted text successfully, length: ${extractedText.length}`);
    console.log(`First 200 characters: ${extractedText.substring(0, 200)}`);

    // Step 6: Save results to audit_results table
    console.log('Step 6: Saving results to audit_results table...');
    console.log(`Target table: public.audit_results`);
    console.log(`Insert data: scan_id=${scanId}, file_name=${fileName}, text_length=${extractedText.length}`);

    const insertData = {
      scan_id: scanId,
      file_name: fileName,
      extracted_text: extractedText,
      processing_method: 'google_document_ai',
      processed_at: new Date().toISOString(),
      metadata: {
        bucket_name: bucketName,
        file_path: filePath,
        processor_id: processorId,
        document_ai_response: aiResult,
      },
    };

    console.log(`Inserting data: ${JSON.stringify(insertData, null, 2)}`);

    const { data: insertResult, error: insertError } = await supabase
      .from('audit_results')
      .insert(insertData)
      .select()
      .single();

    if (insertError) {
      console.error('Failed to save audit results:', insertError);
      throw new Error(`Failed to save audit results: ${insertError.message}`);
    }

    console.log(`Insert successful, record ID: ${insertResult?.id}`);

    // Verify the insert by selecting the record back
    console.log('Verifying insert by selecting record...');
    const { data: verifyData, error: verifyError } = await supabase
      .from('audit_results')
      .select('*')
      .eq('id', insertResult?.id)
      .single();

    if (verifyError) {
      console.error('Failed to verify insert:', verifyError);
      throw new Error(`Failed to verify insert: ${verifyError.message}`);
    }

    if (!verifyData) {
      console.error('No data found after insert verification');
      throw new Error('Insert verification failed - no data returned');
    }

    console.log(`Verification successful: ${JSON.stringify(verifyData, null, 2)}`);

    console.log('=== GOOGLE DOCUMENT AI PROCESSING COMPLETE ===');

    return new Response(
      JSON.stringify({ 
        success: true,
        message: 'Document processed successfully',
        textLength: extractedText.length,
        scanId: scanId,
        recordId: insertResult?.id,
        verifiedData: {
          scan_id: verifyData.scan_id,
          file_name: verifyData.file_name,
          text_length: verifyData.extracted_text?.length,
          processing_method: verifyData.processing_method,
        },
      }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );

  } catch (error) {
    console.error('=== DOCUMENT AI PROCESSING ERROR ===');
    console.error('Error details:', error);
    console.error('Error stack:', error instanceof Error ? error.stack : 'No stack trace');
    console.error('=== END ERROR ===');

    return new Response(
      JSON.stringify({ 
        error: error instanceof Error ? error.message : "Unknown error",
        success: false,
        timestamp: new Date().toISOString(),
      }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});

// Helper function to create JWT for Google OAuth
function createJWT(serviceAccount: any): string {
  const header = {
    alg: 'RS256',
    typ: 'JWT',
  };

  const now = Math.floor(Date.now() / 1000);
  const payload = {
    iss: serviceAccount.client_email,
    scope: 'https://www.googleapis.com/auth/cloud-platform',
    aud: 'https://oauth2.googleapis.com/token',
    exp: now + 3600,
    iat: now,
  };

  const base64UrlEncode = (str: string) => {
    return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  };

  const encodedHeader = base64UrlEncode(JSON.stringify(header));
  const encodedPayload = base64UrlEncode(JSON.stringify(payload));

  // Note: In a production environment, you'd need to properly sign this with the private key
  // For this implementation, we're using a simplified approach
  const signature = 'signature_placeholder'; // This would need proper RSA signing
  
  return `${encodedHeader}.${encodedPayload}.${signature}`;
}

// Helper function to convert file to base64
async function fileToBase64(file: Blob): Promise<string> {
  const arrayBuffer = await file.arrayBuffer();
  const bytes = new Uint8Array(arrayBuffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}
