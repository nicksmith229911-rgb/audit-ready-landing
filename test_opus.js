import { AnthropicVertex } from '@anthropic-ai/vertex-sdk';
import dotenv from 'dotenv';
dotenv.config();

const client = new AnthropicVertex({
  region: 'us-east5',
  project: process.env.GOOGLE_PROJECT_ID, // Using your existing .env ID
  // The SDK automatically looks for GOOGLE_APPLICATION_CREDENTIALS 
  // which we have pointed to google-creds.json
});

async function test() {
  try {
    const message = await client.messages.create({
      max_tokens: 1024,
      messages: [{ role: 'user', content: 'Ping' }],
      model: 'claude-opus-4-1@20250805',
      thinking: { type: 'enabled', budget_tokens: 1024 } // Testing the key feature
    });
    console.log("✅ SUCCESS:", JSON.stringify(message, null, 2));
  } catch (err) {
    console.error("❌ OPUS 4.1 TEST FAILED:", err.message);
    console.error("Full Error:", err);
  }
}
test();
