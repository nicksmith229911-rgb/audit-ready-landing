import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-supabase-client-platform, x-supabase-client-platform-version, x-supabase-client-runtime, x-supabase-client-runtime-version",
};

serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: corsHeaders });
  }

  try {
    console.log('=== ANALYZE-DOCUMENT REDIRECT ===');
    console.log(`Request method: ${req.method}`);
    console.log(`Request URL: ${req.url}`);
    
    // Redirect all requests to audit-engine
    const auditEngineUrl = 'https://mqgnoxybutzyagmdektw.supabase.co/functions/v1/audit-engine';
    
    // Forward the request with same body and headers
    const forwardedResponse = await fetch(auditEngineUrl, {
      method: req.method,
      headers: req.headers,
      body: req.body,
    });

    if (!forwardedResponse.ok) {
      const errorText = await forwardedResponse.text();
      console.error('Failed to forward request to audit-engine:', errorText);
      return new Response(
        JSON.stringify({ error: `Failed to forward to audit-engine: ${forwardedResponse.status}` }),
        { status: forwardedResponse.status, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // Return the response from audit-engine
    const responseData = await forwardedResponse.text();
    
    console.log('Request forwarded to audit-engine successfully');
    console.log('=== ANALYZE-DOCUMENT REDIRECT COMPLETE ===');

    return new Response(responseData, {
      status: forwardedResponse.status,
      headers: {
        ...forwardedResponse.headers,
        ...corsHeaders,
      },
    });

  } catch (error) {
    console.error('=== ANALYZE-DOCUMENT REDIRECT ERROR ===');
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
