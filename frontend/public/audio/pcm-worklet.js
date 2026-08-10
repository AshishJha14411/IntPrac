/**
 * Pulls raw PCM off the audio thread and hands it to the main thread.
 *
 * An AudioWorklet rather than the older ScriptProcessorNode, which every
 * vosk-browser example still uses: ScriptProcessorNode runs on the *main*
 * thread, so a React re-render or a slow paint drops audio frames. Dropped
 * frames are dropped words, dropped words are a wrong transcript, and a wrong
 * transcript is a wrong score — see ADR 011 on why that is the failure this
 * pipeline cares about most.
 *
 * Plain JS on purpose: worklets are loaded by URL into a separate global
 * scope, so this file is not part of the TypeScript build.
 */
class PcmWorklet extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0]?.[0];
    // `channel` is reused between callbacks, so it must be copied before it
    // crosses the port — otherwise the receiver reads whatever came next.
    if (channel && channel.length) this.port.postMessage(channel.slice(0));
    // Keep the node alive even through silence; returning false retires it.
    return true;
  }
}

registerProcessor("pcm-worklet", PcmWorklet);
