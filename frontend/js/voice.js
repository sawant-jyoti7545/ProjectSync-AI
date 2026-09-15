/* ==========================================================================
   ProjectSync AI - Voice Input logic

   Uses the browser's built-in SpeechRecognition API (Chrome/Edge only -
   there is no universal free speech-to-text API, and adding a paid
   third-party service would break the "works offline / no extra keys"
   demo requirement). Falls back to a plain editable textarea in
   unsupported browsers, so voice-capable input degrades gracefully into
   manual text entry rather than breaking the page.

   The resulting transcript is sent to POST /upload-voice, which runs it
   through the exact same match/progress/risk pipeline as a PDF upload -
   see js/upload.js's runProcessingPipeline(), which this reuses.
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
  const micBtn = document.getElementById('mic-btn');
  const micLabel = document.getElementById('mic-label');
  const micIcon = document.getElementById('mic-icon');
  const micStatus = document.getElementById('mic-status');
  const transcriptBox = document.getElementById('voice-transcript');
  const analyzeVoiceBtn = document.getElementById('analyze-voice-btn');
  const unsupportedNotice = document.getElementById('voice-unsupported');

  const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;

  transcriptBox.addEventListener('input', () => {
    analyzeVoiceBtn.disabled = transcriptBox.value.trim().length === 0;
  });

  if (!SpeechRecognitionAPI) {
    unsupportedNotice.classList.remove('hidden');
    micBtn.disabled = true;
    micLabel.textContent = 'Not available';
  } else {
    const recognition = new SpeechRecognitionAPI();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    let isRecording = false;
    let baseTranscript = ''; // text already finalized before this recording session

    micBtn.addEventListener('click', () => {
      if (isRecording) {
        recognition.stop();
      } else {
        baseTranscript = transcriptBox.value ? transcriptBox.value + ' ' : '';
        recognition.start();
      }
    });

    recognition.addEventListener('start', () => {
      isRecording = true;
      micIcon.textContent = '■';
      micLabel.textContent = 'Stop Recording';
      micBtn.classList.remove('btn-primary');
      micBtn.classList.add('btn-secondary');
      micStatus.textContent = 'Listening...';
    });

    recognition.addEventListener('result', (event) => {
      let interim = '';
      let final = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const text = event.results[i][0].transcript;
        if (event.results[i].isFinal) final += text;
        else interim += text;
      }
      baseTranscript += final;
      transcriptBox.value = baseTranscript + interim;
      analyzeVoiceBtn.disabled = transcriptBox.value.trim().length === 0;
    });

    recognition.addEventListener('error', (event) => {
      console.error('[ProjectSync] Speech recognition error:', event.error);
      micStatus.textContent = `Error: ${event.error}. You can type instead.`;
    });

    recognition.addEventListener('end', () => {
      isRecording = false;
      micIcon.textContent = '●';
      micLabel.textContent = 'Start Recording';
      micBtn.classList.remove('btn-secondary');
      micBtn.classList.add('btn-primary');
      micStatus.textContent = transcriptBox.value.trim() ? 'Recording stopped. Review and edit below, then analyze.' : '';
    });
  }

  analyzeVoiceBtn.addEventListener('click', () => {
    const transcript = transcriptBox.value.trim();
    if (!transcript) return;
    runProcessingPipeline(() => callApi('/upload-voice', {
      method: 'POST',
      body: JSON.stringify({ transcript }),
    }));
  });
});
