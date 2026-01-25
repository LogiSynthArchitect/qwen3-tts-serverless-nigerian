/**
 * Cloudflare Worker: OpenAI TTS API → RunPod Qwen3-TTS Bridge
 *
 * Translates OpenAI Text-to-Speech API requests to RunPod Qwen3-TTS format
 * and returns OpenAI-compatible responses (raw audio bytes).
 */

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

/**
 * Handle OpenAI TTS Request
 */
async function handleOpenAITTS(request, env) {
  try {
    // 1. Validate Env
    if (!env.RUNPOD_URL || !env.RUNPOD_API_KEY) {
      console.error('CRITICAL: RunPod configuration missing!');
      return openaiError('Server configuration error', 'server_error', null);
    }

    const apiKeyPreview = env.RUNPOD_API_KEY.substring(0, 4) + '...' + env.RUNPOD_API_KEY.substring(env.RUNPOD_API_KEY.length - 4);
    console.log(`Configured RunPod URL: ${env.RUNPOD_URL}, API Key: ${apiKeyPreview}`);

    // 2. Parse Request
    const openaiRequest = await request.json();
    const { model, input, voice, response_format = 'mp3', stream = false } = openaiRequest;

    if (!input || !voice) {
      return openaiError('Missing required parameters', 'invalid_request_error', null);
    }

    // 3. Map Voice/Mode
    let targetVoice = voice;
    let mode = 'custom_voice';
    
    const QWEN3TTS_SPEAKERS = ["Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric", "Ryan", "Aiden", "Ono_Anna", "Sohee"];
    const mapping = { 'alloy': 'Ryan', 'echo': 'Aiden', 'fable': 'Vivian', 'onyx': 'Uncle_Fu', 'nova': 'Serena', 'shimmer': 'Ono_Anna' };
    
    if (mapping[voice]) {
      targetVoice = mapping[voice];
      mode = 'custom_voice';
    } else if (QWEN3TTS_SPEAKERS.includes(voice)) {
      targetVoice = voice;
      mode = 'custom_voice';
    } else {
      targetVoice = voice;
      mode = 'voice_clone';
    }

    console.log(`Request: voice=${voice}→${targetVoice}, mode=${mode}, text_len=${input.length}, stream=${stream}`);

    // 4. Delegate to Streaming or Batch
    if (stream) {
      return handleOpenAIStreaming(env, {
        text: input,
        mode: mode,
        voice: targetVoice,
        output_format: response_format === 'pcm' ? 'pcm_16' : 'mp3'
      });
    }

    // --- BATCH MODE (Async /run + Poll) ---
    const runpodRequest = {
      input: {
        text: input,
        mode: mode,
        language: 'Auto',
        stream: false,
        ...(mode === 'custom_voice' ? { speaker: targetVoice } : { voice: targetVoice })
      }
    };

    const runUrl = env.RUNPOD_URL.replace(/\/runsync$/, '/run').replace(/\/$/, '') + (env.RUNPOD_URL.endsWith('/run') ? '' : '/run');
    console.log(`Submitting async job to: ${runUrl}`);

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
      console.error(`RunPod /run failed: ${runResponse.status}. Body: ${errorText}`);
      return openaiError(`RunPod gateway error: ${runResponse.status}`, 'server_error', null);
    }

    const jobData = await runResponse.json();
    console.log(`Job submitted. ID: ${jobData.id}, Status: ${jobData.status}`);

    return await pollJobStatus(jobData.id, env);

  } catch (error) {
    console.error('Worker error:', error);
    return openaiError(error.message, 'server_error', null);
  }
}

/**
 * Poll RunPod job status until completion
 */
async function pollJobStatus(jobId, env) {
  const statusUrl = env.RUNPOD_URL.replace(/\/(run|runsync)$/, '').replace(/\/$/, '') + `/status/${jobId}`;
  console.log(`Polling status at: ${statusUrl}`);

  // Cloudflare limit: 50 subrequests.
  // We use 3s interval * 40 attempts = 120s max wait.
  // This uses at most 40 subrequests, safe under the 50 limit.
  const maxAttempts = 40; 
  const pollInterval = 3000;

  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(r => setTimeout(r, pollInterval));

    const resp = await fetch(statusUrl, {
      headers: { 'Authorization': `Bearer ${env.RUNPOD_API_KEY}` }
    });

    if (!resp.ok) {
      console.warn(`Status poll ${i} failed: ${resp.status}`);
      continue;
    }

    const data = await resp.json();
    
    if (data.status === 'COMPLETED') {
      console.log('Job completed successfully.');
      return handleJobOutput(data.output);
    }

    if (data.status === 'FAILED') {
      console.error('Job failed on RunPod:', JSON.stringify(data, null, 2));
      return openaiError('Inference failed on backend', 'server_error', null);
    }

    if (i % 5 === 0) console.log(`Job ${jobId} still ${data.status}...`);
  }

  return openaiError('Job timed out after 2 minutes', 'server_error', null);
}

/**
 * Handle completed job output
 */
async function handleJobOutput(output) {
  let result = Array.isArray(output) ? output[output.length - 1] : output;
  
  if (!result || result.error) {
    console.error('Backend returned logical error:', result?.error || 'Empty output');
    return openaiError(result?.error || 'Backend failed', 'server_error', null);
  }

  let audioBytes;
  if (result.audio_url) {
    console.log('Fetching audio from:', result.audio_url);
    const audioResp = await fetch(result.audio_url);
    if (!audioResp.ok) return openaiError('Failed to fetch audio from storage', 'server_error', null);
    audioBytes = await audioResp.arrayBuffer();
  } else if (result.audio_base64 || result.audio) {
    audioBytes = base64ToArrayBuffer(result.audio_base64 || result.audio);
  } else {
    return openaiError('No audio data in response', 'server_error', null);
  }

  return new Response(audioBytes, {
    headers: { 'Content-Type': 'audio/mpeg', 'Access-Control-Allow-Origin': '*' }
  });
}

/**
 * Handle Streaming OpenAI Response
 */
async function handleOpenAIStreaming(env, params) {
  const { text, mode, voice, output_format } = params;
  const runUrl = env.RUNPOD_URL.replace(/\/(runsync|run)$/, '').replace(/\/$/, '') + '/run';
  const streamBaseUrl = env.RUNPOD_URL.replace(/\/(runsync|run)$/, '').replace(/\/$/, '') + '/stream';

  const runpodRequest = {
    input: {
      text, mode, language: 'Auto', output_format, stream: true,
      ...(mode === 'custom_voice' ? { speaker: voice } : { voice: voice })
    }
  };

  const runResponse = await fetch(runUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${env.RUNPOD_API_KEY}` },
    body: JSON.stringify(runpodRequest)
  });

  if (!runResponse.ok) return openaiError(`Stream submit failed: ${runResponse.status}`, 'server_error', null);

  const jobData = await runResponse.json();
  const streamUrl = `${streamBaseUrl}/${jobData.id}`;
  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();

  // Polling Stream
  (async () => {
    try {
      let lastPos = 0;
      let isFinished = false;
      const startTime = Date.now();
      const pollInterval = 2000; // 2s interval to stay under limits

      while (!isFinished && (Date.now() - startTime) < 300000) {
        const resp = await fetch(streamUrl, { headers: { 'Authorization': `Bearer ${env.RUNPOD_API_KEY}` } });
        if (!resp.ok) break;

        const data = await resp.json();
        const stream = (data.stream || []).concat(data.output || []);

        if (stream.length > lastPos) {
          for (const item of stream.slice(lastPos)) {
            const payload = item?.output || item;
            if (payload.audio_chunk) {
              await writer.write(new Uint8Array(base64ToArrayBuffer(payload.audio_chunk)));
            } else if (payload.error) {
              console.error('Stream item error:', payload.error);
            }
          }
          lastPos = stream.length;
        }

        if (data.status === 'COMPLETED' || data.status === 'FAILED') isFinished = true;
        if (!isFinished) await new Promise(r => setTimeout(r, pollInterval));
      }
    } catch (e) {
      console.error('Stream polling error:', e);
    } finally {
      await writer.close();
    }
  })();

  return new Response(readable, {
    headers: { 'Content-Type': output_format === 'mp3' ? 'audio/mpeg' : 'audio/pcm', 'Transfer-Encoding': 'chunked', 'Access-Control-Allow-Origin': '*' }
  });
}

/**
 * Handle Custom Streaming TTS Endpoint
 */
async function handleStreamingTTS(request, env) {
  try {
    const p = await request.json();
    if (!p.text) return errorResponse('Missing text', 400);

    return handleOpenAIStreaming(env, {
      text: p.text,
      mode: p.mode || 'custom_voice',
      voice: p.speaker || p.voice || 'Ryan',
      output_format: p.output_format || 'mp3'
    });
  } catch (e) {
    return errorResponse(e.message, 500);
  }
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
    JSON.stringify({ error: { message, type, param, code: null } }),
    { status: type === 'invalid_request_error' ? 400 : 500, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } }
  );
}

function errorResponse(message, status) {
  return new Response(JSON.stringify({ error: message }), { status, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
}

function base64ToArrayBuffer(base64) {
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}
