// ------------------------------------------------------------
// aiStream.js
// Phase 8 — AI Pacing Engine Enhancements
// ------------------------------------------------------------

// 1. Pacing Profiles — each message type has its own rhythm
export const pacingProfiles = {
    fact: {
        base: 12,
        perChar: 4,
        punctuation: 120,
        anticipation: 80
    },
    insight: {
        base: 40,
        perChar: 8,
        punctuation: 180,
        anticipation: 140
    },
    warning: {
        base: 60,
        perChar: 10,
        punctuation: 220,
        anticipation: 200
    },
    summary: {
        base: 20,
        perChar: 6,
        punctuation: 150,
        anticipation: 100
    },
    transition: {
        base: 30,
        perChar: 5,
        punctuation: 160,
        anticipation: 120
    },
    punchline: {
        base: 10,
        perChar: 3,
        punctuation: 300,
        anticipation: 250
    }
};

// ------------------------------------------------------------
// 2. Detect punctuation at the end of a chunk
// ------------------------------------------------------------
function endsWithPunctuation(text) {
    return /[.,!?;:]/.test(text.slice(-1));
}

// ------------------------------------------------------------
// 3. Calculate delay for a given text chunk
// ------------------------------------------------------------
export function calculateDelay(text, type = "fact") {
    const profile = pacingProfiles[type] || pacingProfiles.fact;

    let delay = profile.base + text.length * profile.perChar;

    if (endsWithPunctuation(text)) {
        delay += profile.punctuation;
    }

    return delay;
}

// ------------------------------------------------------------
// 4. Anticipation delay — used before important messages
// ------------------------------------------------------------
export function anticipationDelay(type = "fact") {
    const profile = pacingProfiles[type] || pacingProfiles.fact;
    return profile.anticipation;
}

// ------------------------------------------------------------
// 5. Split text into streamable chunks
// ------------------------------------------------------------
export function chunkText(text) {
    return text
        .split(/(\s+)/) // keep spaces as separate tokens
        .filter(chunk => chunk.length > 0);
}

// ------------------------------------------------------------
// 6. Stream generator — yields chunks with delays
// ------------------------------------------------------------
export async function* streamText(text, type = "fact") {
    const chunks = chunkText(text);

    for (const chunk of chunks) {
        const delay = calculateDelay(chunk, type);
        await new Promise(resolve => setTimeout(resolve, delay));
        yield chunk;
    }
}

// ------------------------------------------------------------
// 7. High-level streaming function
// ------------------------------------------------------------
export async function streamMessage(message, type, onChunk) {
    // anticipation pause before important messages
    if (type !== "fact") {
        const anticipation = anticipationDelay(type);
        await new Promise(resolve => setTimeout(resolve, anticipation));
    }

    for await (const chunk of streamText(message, type)) {
        onChunk(chunk);
    }
}
