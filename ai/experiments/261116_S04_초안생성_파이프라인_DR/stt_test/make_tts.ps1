Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice("Microsoft Heami Desktop")
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$items = Get-Content -Raw -Encoding UTF8 sentences.json | ConvertFrom-Json
foreach ($it in $items) { $s.SetOutputToWaveFile((Join-Path (Get-Location) ("audio\" + $it.id + "_clean.wav")), $fmt); $s.Speak($it.text) }
$s.SetOutputToNull()
