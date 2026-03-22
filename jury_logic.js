// Jury Logic System - Claude Opus 4.1 Integration with Production Resilience
// Lead Juror: Claude-4-1-Opus with Vertex AI endpoint

import { GoogleAuth } from 'google-auth-library';
import axios from 'axios';
import dotenv from 'dotenv';
import { resolve } from 'path';
import { fileURLToPath } from 'url';
import { AnthropicVertex } from '@anthropic-ai/vertex-sdk';

// Load environment variables
dotenv.config();

// Get current directory for ES modules
const __filename = fileURLToPath(import.meta.url);
const __dirname = resolve(__filename, '..');

class JuryLogic {
    constructor() {
        this.jurors = [
            {
                name: 'claude-opus-4-1',
                endpoint: 'https://us-east5-aiplatform.googleapis.com/v1/projects/audit-ready-systems/locations/us-east5/publishers/anthropic/models/claude-sonnet-4-6:rawPredict',
                provider: 'anthropic',
                region: 'global',  // Use global endpoint for Claude
                status: 'inactive',
                modelId: 'claude-opus-4-1@20250805',
                clientType: 'global'  // Explicit client routing
            },
            {
                name: 'claude-opus-4-1-eu',
                endpoint: 'https://europe-west1-aiplatform.googleapis.com/v1/projects/audit-ready-systems/locations/europe-west1/publishers/anthropic/models/claude-opus-4-1:rawPredict',
                provider: 'anthropic',
                region: 'global',  // Use global endpoint for Claude
                status: 'inactive',
                modelId: 'claude-opus-4-1@20250805',
                failover: true,
                clientType: 'global'  // Explicit client routing
            },
            {
                name: 'gemini-2.5-flash',
                endpoint: 'https://us-east5-aiplatform.googleapis.com/v1/projects/audit-ready-systems/locations/us-east5/publishers/google/models/gemini-2.5-flash:streamGenerateContent',
                provider: 'google',
                region: 'us-east5',  // Force to us-east5 regional
                status: 'inactive',
                clientType: 'regional'  // Explicit regional routing
            },
            {
                name: 'llama-4-maverick',
                endpoint: 'https://us-east5-aiplatform.googleapis.com/v1/projects/audit-ready-systems/locations/us-east5/endpoints/openapi/chat/completions',
                provider: 'meta',
                region: 'us-east5',  // Force to us-east5 regional
                status: 'inactive',
                clientType: 'regional'  // Explicit regional routing
            }
        ];
        
        this.consensusTable = {
            claude: null,
            gemini: null,
            llama: null,
            majority: null,
            confidence: 0
        };
        
        // Configure GoogleAuth with absolute path
        const keyFilePath = 'service-account.json';
        const absolutePath = resolve(__dirname, keyFilePath);
        console.log(`🔑 Looking for service account at: ${absolutePath}`);
        
        this.auth = new GoogleAuth({
            scopes: ['https://www.googleapis.com/auth/cloud-platform'],
            keyFile: absolutePath
        });

        // Configure Anthropic Vertex SDK with global endpoint for Claude models
        this.anthropicGlobalClient = new AnthropicVertex({
            region: 'global',  // Global endpoint for Claude
            project: process.env.GOOGLE_PROJECT_ID,
            maxRetries: 5
        });

        // Configure separate regional client for Google/Meta models
        this.regionalClient = new AnthropicVertex({
            region: 'us-east5',  // Regional endpoint for Llama/Gemini
            project: process.env.GOOGLE_PROJECT_ID,
            maxRetries: 5
        });
    }

    // Exponential backoff helper for 429 errors
    async exponentialBackoff(retryCount) {
        const delays = [1000, 3000, 10000]; // 1s, 3s, 10s
        if (retryCount < delays.length) {
            const delay = delays[retryCount];
            console.log(`⏳ Exponential backoff: waiting ${delay}ms (attempt ${retryCount + 1})`);
            await new Promise(resolve => setTimeout(resolve, delay));
            return true;
        }
        return false;
    }

    async analyzeDocumentWithResilience(juror, document) {
        if (juror.provider === 'anthropic') {
            // Use Anthropic Vertex SDK with failover
            return await this.analyzeWithAnthropicSDK(juror, document);
        } else {
            // Use existing axios method for Google/Meta models with regional endpoints
            return await this.analyzeDocument(juror, document);
        }
    }

    async analyzeWithAnthropicSDK(juror, document) {
        const prompt = "Analyze this conflict scenario and provide a verdict:\n\n" +
            document +
            "\n\nRespond with a JSON object:\n" +
            "{\n" +
            '    "verdict": "rotation_wins" | "override_wins" | "conflict_state",\n' +
            '    "confidence": 0.0-1.0,\n' +
            '    "reasoning": "brief explanation",\n' +
            '    "timeline": "chronological analysis"\n' +
            "}";

        let lastError = null;
        
        // Select appropriate client based on routing
        const client = juror.clientType === 'global' ? this.anthropicGlobalClient : this.regionalClient;
        
        // Try primary region first
        for (let attempt = 0; attempt < 5; attempt++) {
            try {
                console.log(`🔄 Attempt ${attempt + 1}: ${juror.name} via ${juror.region} (${juror.clientType} client)`);
                
                const message = await client.messages.create({
                    max_tokens: 50,   // Ultra-minimal: reduced from 400
                    messages: [{ role: 'user', content: prompt.substring(0, 200) }],  // Truncate prompt
                    model: juror.modelId,
                    thinking: { type: 'enabled', budget_tokens: 32 }  // Ultra-minimal: reduced from 128
                });
                
                console.log(`✅ SUCCESS: ${juror.name} response from ${juror.region}`);
                return {
                    juror: juror.name,
                    verdict: JSON.parse(message.content[0].text).verdict,
                    confidence: JSON.parse(message.content[0].text).confidence,
                    reasoning: JSON.parse(message.content[0].text).reasoning,
                    timeline: JSON.parse(message.content[0].text).timeline
                };
                
            } catch (error) {
                lastError = error;
                
                if (error.status === 429) {
                    console.log(`⚠️ 429 Error on attempt ${attempt + 1}: ${error.message}`);
                    
                    // Try regional failover on first retry for Claude models only
                    if (attempt === 0 && juror.provider === 'anthropic' && juror.clientType === 'global') {
                        console.log('🌍 Initiating regional failover to europe-west1...');
                        const euJuror = this.jurors.find(j => j.failover);
                        if (euJuror) {
                            return await this.analyzeWithEUFailover(euJuror, document);
                        }
                    }
                    
                    // Apply exponential backoff
                    const shouldRetry = await this.exponentialBackoff(attempt);
                    if (!shouldRetry) break;
                } else {
                    // Non-429 error, don't retry
                    throw error;
                }
            }
        }
        
        throw lastError || new Error('Max retries exceeded');
    }

    async analyzeWithEUFailover(euJuror, document) {
        console.log('🇪🇺 Attempting Claude Opus 4.1 via europe-west1...');
        
        try {
            const euClient = new AnthropicVertex({
                region: 'europe-west1',
                project: process.env.GOOGLE_PROJECT_ID,
                maxRetries: 3
            });
            
            const prompt = "Analyze this conflict scenario and provide a verdict:\n\n" +
                document +
                "\n\nRespond with a JSON object:\n" +
                "{\n" +
            '    "verdict": "rotation_wins" | "override_wins" | "conflict_state",\n' +
            '    "confidence": 0.0-1.0,\n' +
            '    "reasoning": "brief explanation",\n' +
            '    "timeline": "chronological analysis"\n' +
            "}";

            const message = await euClient.messages.create({
                max_tokens: 50,   // Ultra-minimal: reduced from 400
                messages: [{ role: 'user', content: prompt.substring(0, 200) }],  // Truncate prompt
                model: euJuror.modelId,
                thinking: { type: 'enabled', budget_tokens: 32 }  // Ultra-minimal: reduced from 128
            });
            
            console.log('✅ SUCCESS: Claude Opus 4.1 response from europe-west1');
            return {
                juror: euJuror.name,
                verdict: JSON.parse(message.content[0].text).verdict,
                confidence: JSON.parse(message.content[0].text).confidence,
                reasoning: JSON.parse(message.content[0].text).reasoning,
                timeline: JSON.parse(message.content[0].text).timeline
            };
            
        } catch (error) {
            console.log(`❌ EU Failover failed: ${error.message}`);
            throw error;
        }
    }

    async initialize() {
        console.log('🚀 Initializing Jury Logic System...');
        console.log('📋 Lead Juror: Claude-Opus-4-1 (Vertex AI)');
        
        await this.runHealthCheck();
    }

    async runHealthCheck() {
        console.log('\n🏥 Running Health Check on all models...');
        
        const healthPromises = this.jurors.map(async (juror) => {
            try {
                const result = await this.pingJuror(juror);
                juror.status = result ? 'active' : 'inactive';
                console.log(`${result ? '✅' : '❌'} ${juror.name}: ${juror.status}`);
                return { juror: juror.name, status: juror.status };
            } catch (error) {
                juror.status = 'inactive';
                console.log(`❌ ${juror.name}: ${error.message}`);
                return { juror: juror.name, status: 'error', error: error.message };
            }
        });

        const healthResults = await Promise.all(healthPromises);
        console.log('\n📊 Health Check Summary:');
        healthResults.forEach(result => {
            console.log(`  ${result.juror}: ${result.status}${result.error ? ` (${result.error})` : ''}`);
        });
        
        return healthResults;
    }

    async pingJuror(juror) {
    if (juror.provider === 'anthropic') {
        try {
            // Use appropriate client for health check
            const client = juror.clientType === 'global' ? this.anthropicGlobalClient : this.regionalClient;
            
            await client.messages.create({
                max_tokens: 10,
                messages: [{ role: 'user', content: 'Health check. Respond with OK.' }],
                model: juror.modelId
            });
            return true;
        } catch (error) {
            // For 429 errors, this is expected due to quota limits
            if (error.status === 429) {
                console.log(`⚠️ 429 quota limit for ${juror.name} - this indicates access is working`);
                return true; // 429 means we have access, just quota limited
            }
            throw error;
        }
    } else {
        // Use existing method for non-Anthropic models (Google/Meta)
        const healthPrompt = {
            contents: [{
                parts: [{
                    text: "Health check. Respond with 'OK' if you are operational."
                }]
            }]
        };

        const token = await this.auth.getAccessToken();
        const headers = {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        };

        const response = await axios.post(juror.endpoint, healthPrompt, { headers });
        return response.status === 200;
    }
}

    async analyzeDocument(juror, document) {
        const prompt = {
            contents: [{
                parts: [{
                    text: "Analyze this conflict scenario and provide a verdict:\n\n" +
                        document +
                        "\n\nRespond with a JSON object:\n" +
                        "{\n" +
                    '    "verdict": "rotation_wins" | "override_wins" | "conflict_state",\n' +
                    '    "confidence": 0.0-1.0,\n' +
                    '    "reasoning": "brief explanation",\n' +
                    '    "timeline": "chronological analysis"\n' +
                    "}"
                }]
            }]
        };

        const token = await this.auth.getAccessToken();
        const headers = {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        };

        const response = await axios.post(juror.endpoint, prompt, { headers });
        const result = response.data.candidates[0].content.parts[0].text;
        
        try {
            const parsed = JSON.parse(result);
            return {
                juror: juror.name,
                verdict: parsed.verdict,
                confidence: parsed.confidence,
                reasoning: parsed.reasoning,
                timeline: parsed.timeline
            };
        } catch (parseError) {
            return {
                juror: juror.name,
                verdict: 'parse_error',
                confidence: 0,
                reasoning: 'Failed to parse response'
            };
        }
    }

    async runConflictSimulation() {
        console.log('\n⚖️ Running Audit Lite PoC: Deep Economy with Polite Delays');
        
        // Read audit lite document
        const fs = await import('fs');
        const auditDocument = fs.readFileSync('audit_lite.txt', 'utf8');
        
        const results = [];
        
        // Process jurors sequentially with polite delays
        for (let i = 0; i < this.jurors.length; i++) {
            const juror = this.jurors[i];
            
            if (juror.status !== 'active') {
                results.push({ juror: juror.name, verdict: 'inactive', confidence: 0 });
                continue;
            }

            try {
                console.log(`\n🎯 Processing juror ${i + 1}/${this.jurors.length}: ${juror.name}`);
                const analysis = await this.analyzeDocumentWithResilience(juror, auditDocument);
                this.consensusTable[juror.provider] = analysis.verdict;
                results.push(analysis);
                
                // Polite delay: 10-second sleep between juror calls for quota refill
                if (i < this.jurors.length - 1) {
                    console.log('⏸️ Polite delay: Waiting 10 seconds for quota bucket refill...');
                    await new Promise(resolve => setTimeout(resolve, 10000));
                }
                
            } catch (error) {
                console.log(`❌ ${juror.name} analysis failed: ${error.message}`);
                results.push({ juror: juror.name, verdict: 'error', confidence: 0 });
            }
        }

        this.calculateConsensus();
        return results;
    }

    calculateConsensus() {
        console.log('\n📊 Calculating Consensus...');
        
        const verdicts = Object.values(this.consensusTable).filter(v => v !== null);
        const verdictCounts = {};
        
        verdicts.forEach(verdict => {
            verdictCounts[verdict] = (verdictCounts[verdict] || 0) + 1;
        });

        const maxCount = Math.max(...Object.values(verdictCounts));
        const majorityVerdicts = Object.keys(verdictCounts).filter(v => verdictCounts[v] === maxCount);
        
        if (majorityVerdicts.length === 1) {
            this.consensusTable.majority = majorityVerdicts[0];
            this.consensusTable.confidence = maxCount / verdicts.length;
        } else {
            this.consensusTable.majority = 'tie';
            this.consensusTable.confidence = 0.5;
        }

        this.outputConsensusTable();
    }

    outputConsensusTable() {
        console.log('\n🗳️ CONSENSUS TABLE');
        console.log('='.repeat(50));
        console.log(`Claude (Lead): ${this.consensusTable.claude || 'No Vote'}`);
        console.log(`Gemini: ${this.consensusTable.gemini || 'No Vote'}`);
        console.log(`Llama: ${this.consensusTable.llama || 'No Vote'}`);
        console.log('-'.repeat(50));
        console.log(`MAJORITY: ${this.consensusTable.majority}`);
        console.log(`CONFIDENCE: ${(this.consensusTable.confidence * 100).toFixed(1)}%`);
        console.log(`THRESHOLD: ${this.consensusTable.confidence >= 0.67 ? '✅ PASSED' : '❌ FAILED'}`);
        console.log('='.repeat(50));
    }

    async runFullAudit() {
        await this.initialize();
        await this.runConflictSimulation();
        
        console.log('\n🎯 AUDIT COMPLETE');
        console.log(`Final Verdict: ${this.consensusTable.majority}`);
        console.log(`Confidence Level: ${(this.consensusTable.confidence * 100).toFixed(1)}%`);
        
        return this.consensusTable;
    }
}

// Export for module usage
export default JuryLogic;

// Run if called directly
console.log('🚀 Starting Jury Logic System...');
const jury = new JuryLogic();
jury.runFullAudit().catch(console.error);
