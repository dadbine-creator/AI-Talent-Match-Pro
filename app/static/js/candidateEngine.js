// ------------------------------------------------------------
// candidateEngine.js
// Connects backend AI → pacing engine → UI renderer
// ------------------------------------------------------------

import { streamMessage } from "./aiStream.js";

// ------------------------------------------------------------
// 1. Message Type Classifier
// ------------------------------------------------------------
// This determines which pacing profile to use for each message.
// You can expand this anytime.
// ------------------------------------------------------------

export function classifyMessage(text) {
    const lower = text.toLowerCase();

    if (lower.includes("warning") || lower.includes("caution")) {
        return "warning";
    }
    if (lower.includes("insight") || lower.includes("interesting")) {
        return "insight";
    }
    if (lower.includes("summary") || lower.includes("overall")) {
        return "summary";
    }
    if (lower.includes("next") || lower.includes("now")) {
        return "transition";
    }
    if (lower.endsWith("!")) {
        return "punchline";
    }

    return "fact"; // default
}

// ------------------------------------------------------------
// 2. Fetch AI Response From Backend
// ------------------------------------------------------------
// This calls your Flask/FastAPI backend at /api/stream
// and returns the full text response.
// ------------------------------------------------------------

export async function fetchAIResponse(prompt) {
    const response = await fetch("/api/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt })
    });

    if (!response.ok) {
        throw new Error("AI request failed");
    }

    const data = await response.json();
    return data.message; // backend returns { message: "..." }
}

// ------------------------------------------------------------
// 3. Stream AI Response Into UI
// ------------------------------------------------------------
// This is the main function your UI calls.
// It streams the AI output chunk-by-chunk using the pacing engine.
// ------------------------------------------------------------

export async function processAIResponse(prompt, onChunk) {
    try {
        // 1. Get full AI message from backend
        const fullMessage = await fetchAIResponse(prompt);

        // 2. Determine pacing type
        const type = classifyMessage(fullMessage);

        // 3. Stream message chunk-by-chunk
        await streamMessage(fullMessage, type, onChunk);

        return true;

    } catch (err) {
        console.error("AI Stream Error:", err);
        onChunk("\n[Error: Could not load AI response]");
        return false;
    }
}

// ------------------------------------------------------------
// 4. Utility: Clean Prompt Before Sending
// ------------------------------------------------------------

export function sanitizePrompt(text) {
    return text.trim();
}
