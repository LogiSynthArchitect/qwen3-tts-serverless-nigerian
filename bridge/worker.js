/**
 * Cloudflare Worker: OpenAI TTS API → RunPod Qwen3-TTS Bridge
 *
 * Translates OpenAI Text-to-Speech API requests to RunPod Qwen3-TTS format
 * and returns OpenAI-compatible responses (raw audio bytes).
 *
 * Supports streaming via RunPod Serverless streaming protocol.
 */

// Cache for voice mappings (5 minute TTL)
let voiceMappingCache = null;
let lastFetch = 0;
const CACHE_TTL = 5 * 60 * 1000; // 5 minutes

// Qwen3-TTS CustomVoice speakers
const QWEN3TTS_SPEAKERS = [
    "Vivian",      // Bright, slightly edgy young female (Chinese)
    "Serena",      // Warm, gentle young female (Chinese)
    "Uncle_Fu",    // Seasoned male, low/mellow timbre (Chinese)
    "Dylan",       // Youthful Beijing male, clear/natural (Chinese)
    "Eric",        // Lively Chengdu male, husky/bright (Chinese)
    "Ryan",        // Dynamic male, strong rhythmic drive (English)
    "Aiden",       // Sunny American male, clear midrange (English)
    "Ono_Anna",    // Playful Japanese female, light/nimble (Japanese)
    "Sohee",       // Warm Korean female, rich emotion (Korean)
];

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // CORS preflight
    if (request.method === 'OPTIONS') {
      return handleCORS();
    }

    // Health check
    if (url.pathname === '/health') {
      return new Response(JSON.stringify({
        status: 'healthy',
        tier: 'middleware-cloudflare-qwen3tts',
        timestamp: Date.now()
      }), {
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        }
      });
    }

    // Authenticate request (if API_KEY is configured)
    if (env.API_KEY) {
      const authHeader = request.headers.get('Authorization');

      if (!authHeader) {
        return new Response(
          JSON.stringify({
            error: {
              message: 'Missing Authorization header',
              type: 'authentication_error',
              param: null,
              code: 'missing_authorization'
            }
          }),
          {
            status: 401,
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*'
            }
          }
        );
      }

      const token = authHeader.replace(/^Bearer\s+/i, '');

      if (token !== env.API_KEY) {
        return new Response(
          JSON.stringify({
            error: {
              message: 'Invalid authentication token',
              type: 'authentication_error',
              param: null,
              code: 'invalid_token'
            }
          }),
          {
            status: 401,
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*'
            }
          }
        );
      }
    }

    // Route: OpenAI TTS Compatible Endpoint
    if (request.method === 'POST' && url.pathname === '/v1/audio/speech') {
      return handleOpenAITTS(request, env);
    }

    // Route: Streaming TTS Endpoint
    if (request.method === 'POST' && url.pathname === '/api/tts/stream') {
      return handleStreamingTTS(request, env);
    }

    return errorResponse('Not found. Available endpoints: POST /v1/audio/speech, POST /api/tts/stream', 404);
  }
};

async function handleOpenAITTS(request, env) {
  try {
    // Parse OpenAI TTS request
    const openaiRequest = await request.json();

    // Validate required fields
    const { model, input, voice, response_format = 'mp3', speed = 1.0, stream = false } = openaiRequest;

    if (!model) {
      return openaiError('Missing required parameter: model', 'invalid_request_error', 'model');
    }
    if (!input) {
      return openaiError('Missing required parameter: input', 'invalid_request_error', 'input');
    }
    if (!voice) {
      return openaiError('Missing required parameter: voice', 'invalid_request_error', 'voice');
    }

    // Map OpenAI voice to Qwen3-TTS speaker
    const speaker = mapOpenAIVoiceToQwen3TTS(voice);
    if (!speaker) {
      const available = QWEN3TTS_SPEAKERS.join(', ');
      return openaiError(
        `Invalid voice '${voice}'. Available: ${available}`,
        'invalid_request_error',
        'voice'
      );
    }

    // Warn about unsupported features
    if (response_format !== 'mp3' && response_format !== 'pcm') {
      console.warn(`Unsupported response_format: ${response_format}. Only 'mp3' or 'pcm' supported.`);
    }
    if (speed !== 1.0) {
      console.warn(`Speed parameter (${speed}) is not supported and will be ignored.`);
    }

    console.log(`OpenAI TTS request: voice=${voice}→${speaker}, text_len=${input.length}, format=${response_format}, stream=${stream}`);

    // If streaming is requested, delegate to streaming handler
    if (stream) {
      return handleOpenAIStreaming(env, {
        text: input,
        mode: 'custom_voice',
        speaker: speaker,
        output_format: response_format === 'pcm' ? 'pcm_16' : 'mp3'
      });
    }

    // --- BATCH MODE ---

    // Translate to RunPod Qwen3-TTS format
    const runpodRequest = {
      input: {
        text: input,
        mode: 'custom_voice',
        speaker: speaker,
        language: 'Auto',  // Auto-detect language
        // Use default generation parameters
        temperature: 0.9,
        top_k: 50,
        top_p: 1.0,
        repetition_penalty: 1.05,
        do_sample: true,
        max_new_tokens: 2048,
        stream: false
      }
    };

    // Use /runsync for direct synchronous execution
    let syncUrl = env.RUNPOD_URL;
    if (!syncUrl.endsWith('/runsync')) {
      if (syncUrl.endsWith('/run')) {
        syncUrl = syncUrl.slice(0, -4) + '/runsync';
      } else {
        syncUrl = syncUrl.replace(/\/$/, '') + '/runsync';
      }
    }

    console.log(`Using RunPod /runsync endpoint: ${syncUrl}`);

    // Submit job to /runsync
    const runResponse = await fetch(syncUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${env.RUNPOD_API_KEY}`
      },
      body: JSON.stringify(runpodRequest)
    });

    if (!runResponse.ok) {
      const errorText = await runResponse.text();
      console.error('RunPod /runsync error:', errorText);
      return openaiError(
        `RunPod service error: ${runResponse.status} ${runResponse.statusText}`,
        'server_error',
        null
      );
    }

    const jobData = await runResponse.json();

    // Check job status
    if (jobData.status !== 'COMPLETED') {
      console.warn(`Job did not complete synchronously: status=${jobData.status}. Job ID: ${jobData.id}`);
      return handleAsyncPollingFallback(jobData.id, env);
    }

    // Extract from output array
    let output = jobData.output;
    if (Array.isArray(output) && output.length > 0) {
      output = output[output.length - 1];
    }

    console.log('[Batch] /runsync response: status=' + jobData.status + ', output type=' + typeof output);

    // Check for errors
    if (!output || output.error) {
      const error = output?.error || 'Unknown error in RunPod output';
      console.error('RunPod returned error:', error);
      return openaiError(error, 'server_error', null);
    }

    // Extract audio data
    let audioBytes;
    let contentType = 'audio/mpeg';

    if (output.audio_url) {
      // Fetch from S3
      console.log('Fetching audio from S3:', output.audio_url);
      const s3Response = await fetch(output.audio_url);

      if (!s3Response.ok) {
        console.error('Failed to fetch from S3:', s3Response.status);
        return openaiError('Failed to fetch audio from S3', 'server_error', null);
      }

      audioBytes = await s3Response.arrayBuffer();
      contentType = 'audio/mpeg';

    } else if (output.audio_base64 || output.audio) {
      const audioBase64 = output.audio_base64 || output.audio;
      audioBytes = base64ToArrayBuffer(audioBase64);

    } else {
      console.error('No audio data in RunPod response:', output);
      return openaiError('No audio data returned from RunPod', 'server_error', null);
    }

    return new Response(audioBytes, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'no-cache'
      }
    });

  } catch (error) {
    console.error('Worker error:', error);
    return openaiError(error.message, 'server_error', null);
  }
}

/**
 * Handle Streaming OpenAI Response
 * Submits async job, polls for chunks, and pipes raw binary to response body
 */
async function handleOpenAIStreaming(env, params) {
  const { text, mode, speaker, output_format } = params;
  const requestId = crypto.randomUUID();

  // Prepare RunPod URLs
  let runUrl = env.RUNPOD_URL;
  let streamBaseUrl;

  if (runUrl.endsWith('/runsync')) {
    runUrl = runUrl.slice(0, -8) + '/run';
    streamBaseUrl = runUrl.slice(0, -4) + '/stream';
  } else if (runUrl.endsWith('/run')) {
    streamBaseUrl = runUrl.slice(0, -4) + '/stream';
  } else {
    runUrl = runUrl.replace(/\/$/, '') + '/run';
    streamBaseUrl = runUrl.replace(/\/$/, '') + '/stream';
  }

  console.log(`[Streaming][${requestId}] Submitting job to ${runUrl}...`);

  // Submit async job
  const runpodRequest = {
    input: {
      text: text,
      mode: mode,
      speaker: speaker,
      language: 'Auto',
      output_format: output_format,
      stream: true,
      temperature: 0.9,
      top_k: 50,
      top_p: 1.0,
      repetition_penalty: 1.05,
      do_sample: true,
      max_new_tokens: 2048
    }
  };

  const runResponse = await fetch(runUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${env.RUNPOD_API_KEY}`
    },
    body: JSON.stringify(runpodRequest)
  });

  if (!runResponse.ok) {
    const errorText = await runResponse.text();
    console.error('RunPod /run error:', errorText);
    return openaiError(`RunPod service error: ${runResponse.status}`, 'server_error', null);
  }

  const jobData = await runResponse.json();
  const jobId = jobData.id;
  const streamUrl = `${streamBaseUrl}/${jobId}`;

  console.log(`[Streaming][${requestId}] Job submitted: ${jobId}. Polling ${streamUrl}...`);

  // Create a TransformStream for raw binary streaming
  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();

  // Background poller
  (async () => {
    try {
      let lastStreamPosition = 0;
      let lastChunkProcessed = 0;
      let expectedChunks = null;
      let isFinished = false;
      let pollInterval = 500;
      const startTime = Date.now();
      const timeout = 300000; // 5 minutes

      while (!isFinished && (Date.now() - startTime) < timeout) {
        const resp = await fetch(streamUrl, {
          headers: { 'Authorization': `Bearer ${env.RUNPOD_API_KEY}` }
        });

        if (!resp.ok) throw new Error(`Stream poll failed: ${resp.status}`);

        const data = await resp.json();
        const streamData = Array.isArray(data.stream) ? data.stream : [];
        const outputData = Array.isArray(data.output) ? data.output : [];
        const combinedStream = streamData.length ? streamData : outputData;

        const processItems = async (items) => {
          let processedAny = false;
          for (const item of items) {
            const payload = item?.output || item;
            if (!payload) continue;

            if (payload.status === 'streaming') {
              const chunkNum = payload.chunk;
              if (typeof chunkNum === 'number' && chunkNum <= lastChunkProcessed) {
                continue;
              }
              
              if (payload.audio_chunk) {
                const chunkBytes = base64ToArrayBuffer(payload.audio_chunk);
                await writer.write(new Uint8Array(chunkBytes));
                processedAny = true;
                if (typeof chunkNum === 'number') {
                  lastChunkProcessed = Math.max(lastChunkProcessed, chunkNum);
                } else {
                  lastChunkProcessed++;
                }
              }
            } else if (payload.status === 'complete') {
              if (typeof payload.total_chunks === 'number') {
                expectedChunks = payload.total_chunks;
              }
              processedAny = true;
            } else if (payload.error) {
              console.error(`[Streaming][${requestId}] Error in stream:`, payload.error);
            }
          }
          return processedAny;
        };

        if (combinedStream.length > lastStreamPosition) {
          const newItems = combinedStream.slice(lastStreamPosition);
          const processed = await processItems(newItems);
          lastStreamPosition = combinedStream.length;
          pollInterval = processed ? 500 : Math.min(pollInterval * 1.5, 5000);
        }

        if (data.status === 'COMPLETED' || data.status === 'FAILED') {
          // Final poll to catch remaining items
          await new Promise(r => setTimeout(r, 250));
          const finalResp = await fetch(streamUrl, {
            headers: { 'Authorization': `Bearer ${env.RUNPOD_API_KEY}` }
          });
          if (finalResp.ok) {
            const finalData = await finalResp.json();
            const finalCombined = (Array.isArray(finalData.stream) ? finalData.stream : [])
                                 .concat(Array.isArray(finalData.output) ? finalData.output : []);
            if (finalCombined.length > lastStreamPosition) {
              await processItems(finalCombined.slice(lastStreamPosition));
            }
          }
          isFinished = true;
        }

        if (!isFinished) await new Promise(r => setTimeout(r, pollInterval));
      }
    } catch (e) {
      console.error(`[Streaming][${requestId}] Error:`, e);
    } finally {
      await writer.close();
    }
  })();

  return new Response(readable, {
    headers: {
      'Content-Type': output_format === 'mp3' ? 'audio/mpeg' : 'audio/pcm',
      'Transfer-Encoding': 'chunked',
      'Cache-Control': 'no-cache',
      'Access-Control-Allow-Origin': '*'
    }
  });
}

/**
 * Handle Custom Streaming TTS Endpoint
 */
async function handleStreamingTTS(request, env) {
  try {
    const params = await request.json();

    const { text, mode = 'custom_voice', speaker, instruct, language = 'Auto',
            ref_audio, ref_text, output_format = 'mp3' } = params;

    if (!text) {
      return errorResponse('Missing required parameter: text', 400);
    }

    // Validate mode-specific requirements
    if (mode === 'custom_voice' && !speaker) {
      return errorResponse('speaker parameter required for custom_voice mode', 400);
    }
    if (mode === 'voice_design' && !instruct) {
      return errorResponse('instruct parameter required for voice_design mode', 400);
    }
    if (mode === 'voice_clone' && !ref_audio) {
      return errorResponse('ref_audio parameter required for voice_clone mode', 400);
    }

    return handleOpenAIStreaming(env, {
      text,
      mode,
      speaker: speaker || 'Ryan',
      instruct,
      language,
      ref_audio,
      ref_text,
      output_format
    });

  } catch (error) {
    console.error('Streaming TTS error:', error);
    return errorResponse(error.message, 500);
  }
}

/**
 * Map OpenAI voice name to Qwen3-TTS speaker
 */
function mapOpenAIVoiceToQwen3TTS(openaiVoice) {
  const mapping = {
    'alloy': 'Ryan',      // Neutral male
    'echo': 'Aiden',      // Male
    'fable': 'Vivian',    // Female
    'onyx': 'Uncle_Fu',   // Deep male
    'nova': 'Serena',     // Female
    'shimmer': 'Ono_Anna', // Female
  };

  // Return mapped speaker or check if it's already a valid Qwen3-TTS speaker
  return mapping[openaiVoice] || (QWEN3TTS_SPEAKERS.includes(openaiVoice) ? openaiVoice : null);
}

/**
 * Handle async polling fallback for jobs that didn't complete in /runsync
 */
async function handleAsyncPollingFallback(jobId, env) {
  console.warn(`[Fallback] Starting polling for job ${jobId}`);

  const maxAttempts = 60;  // 60 seconds max wait
  const pollInterval = 1000;  // 1 second

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    await new Promise(resolve => setTimeout(resolve, pollInterval));

    const statusUrl = env.RUNPOD_URL.replace(/\/run(sync)?$/, '') + `/status/${jobId}`;
    const statusResponse = await fetch(statusUrl, {
      headers: {
        'Authorization': `Bearer ${env.RUNPOD_API_KEY}`
      }
    });

    if (!statusResponse.ok) {
      continue;
    }

    const statusData = await statusResponse.json();

    if (statusData.status === 'COMPLETED') {
      console.log(`[Fallback] Job completed on attempt ${attempt + 1}`);

      let output = statusData.output;
      if (Array.isArray(output) && output.length > 0) {
        output = output[output.length - 1];
      }

      if (output && output.audio_base64) {
        const audioBytes = base64ToArrayBuffer(output.audio_base64);
        return new Response(audioBytes, {
          status: 200,
          headers: {
            'Content-Type': 'audio/mpeg',
            'Access-Control-Allow-Origin': '*'
          }
        });
      }
    }

    if (statusData.status === 'FAILED') {
      return openaiError('Job failed', 'server_error', null);
    }
  }

  return openaiError('Job timed out', 'server_error', null);
}

function handleCORS() {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      'Access-Control-Max-Age': '86400'
    }
  });
}

function openaiError(message, type, param) {
  return new Response(
    JSON.stringify({
      error: {
        message: message,
        type: type,
        param: param,
        code: type === 'authentication_error' ? 'invalid_token' : null
      }
    }),
    {
      status: type === 'invalid_request_error' ? 400 : 500,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      }
    }
  );
}

function errorResponse(message, status) {
  return new Response(
    JSON.stringify({ error: message }),
    {
      status: status,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      }
    }
  );
}

function base64ToArrayBuffer(base64) {
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}
