param([string]$Pdf, [int]$From, [int]$To, [string]$OutDir, [double]$Scale = 3.0)
# Render PDF pages with Windows.Data.Pdf and OCR with Windows.Media.Ocr (ko). Output: one UTF-8 txt per page + png.
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $m = $asTask.MakeGenericMethod($t); $task = $m.Invoke($null, @($op)); $task.Wait() | Out-Null; $task.Result }
$asTaskA = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
function AwaitA($op) { $task = $asTaskA.Invoke($null, @($op)); $task.Wait() | Out-Null }
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Pdf)) ([Windows.Storage.StorageFile])
$doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
[Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null
$lang = [Windows.Globalization.Language]::new('ko')
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
New-Item -ItemType Directory -Force $OutDir | Out-Null
for ($i = $From; $i -le $To; $i++) {
  $page = $doc.GetPage($i - 1)
  $opts = New-Object Windows.Data.Pdf.PdfPageRenderOptions
  $opts.DestinationWidth = [uint32]($page.Size.Width * $Scale)
  $opts.DestinationHeight = [uint32]($page.Size.Height * $Scale)
  $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
  AwaitA ($page.RenderToStreamAsync($stream, $opts))
  $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  if ($bmp.PixelWidth -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -or $bmp.PixelHeight -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) { Write-Host "page $i too large: $($bmp.PixelWidth)x$($bmp.PixelHeight)" }
  $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
  $lines = $res.Lines | ForEach-Object { $_.Text }
  [System.IO.File]::WriteAllLines((Join-Path $OutDir ("p{0:D3}.txt" -f $i)), [string[]]$lines, (New-Object System.Text.UTF8Encoding $false))
  # save png for visual check
  $pngPath = Join-Path $OutDir ("p{0:D3}.png" -f $i)
  $fs = [System.IO.File]::Create($pngPath)
  $stream.Seek(0)
  $rs = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream)
  $rs.CopyTo($fs); $fs.Close()
  Write-Host "page $i lines=$($res.Lines.Count) size=$($bmp.PixelWidth)x$($bmp.PixelHeight)"
}
