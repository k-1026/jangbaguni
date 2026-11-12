<#
  캡처 이미지 → 글 파일(.md)  (윈도우 기본 글자 인식 OCR, 무료 · 인터넷 안 씀)
  사용:  powershell -ExecutionPolicy Bypass -File tools\ocr\voc_ocr.ps1 -Folder "C:\Users\내이름\Desktop\voc_캡처\팀원A"
  옵션:  -Zoom 3  글씨가 작으면 키워서 읽음 (기본 3배. 카페 캡처는 1배보다 훨씬 잘 읽힘)
  결과:  폴더 안 모든 이미지(png · jpg · jpeg · bmp · gif · webp)를 읽어 폴더 이름.md 한 파일로 (폴더 바로 옆에 저장)
         하위 폴더까지 읽고, 파일마다 "## 파일 이름" 아래에 글이 붙음
  주의:  캡처에는 닉네임 등 개인정보가 있으니 결과 파일도 저장소(GitHub) 밖에 둘 것
#>
param(
  [Parameter(Mandatory = $true)][string]$Folder,
  [string]$Out = "",
  [double]$Zoom = 3.0
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]

# 윈도우 비동기 호출을 기다리는 도우미
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
  $task = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
  $task.Wait(-1) | Out-Null
  $task.Result
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("ko"))
if (-not $engine) { throw "한국어 글자 인식(OCR)이 없어요. 설정 → 시간 및 언어 → 언어에서 한국어 '광학 문자 인식'을 설치해 주세요." }
$max = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension

function Read-Image([string]$path) {
  $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
  $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  try {
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $w = $decoder.PixelWidth; $h = $decoder.PixelHeight
    $lines = @()
    # 세로로 긴 캡처는 인식 한도(MaxImageDimension)보다 길면 위에서부터 잘라 여러 번 읽음
    # 글씨가 작은 캡처는 키워서 읽으면 더 잘 읽힘 (기본 3배, 인식 한도를 넘지 않게)
    $scale = [double]$Zoom
    if ($w * $scale -gt $max) { $scale = $max / $w }
    $sliceH = [Math]::Min($h, [int]($max / $scale))
    for ($top = 0; $top -lt $h; $top += $sliceH) {
      $t = New-Object Windows.Graphics.Imaging.BitmapTransform
      $t.Bounds = New-Object Windows.Graphics.Imaging.BitmapBounds -Property @{ X = 0; Y = [uint32]$top; Width = [uint32]$w; Height = [uint32][Math]::Min($sliceH, $h - $top) }
      if ($scale -ne 1) { $t.ScaledWidth = [uint32]($w * $scale); $t.ScaledHeight = [uint32]($h * $scale)
                           $t.Bounds = New-Object Windows.Graphics.Imaging.BitmapBounds -Property @{ X = 0; Y = [uint32]($top * $scale); Width = [uint32]($w * $scale); Height = [uint32]([Math]::Min($sliceH, $h - $top) * $scale) } }
      $bmp = Await ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8, [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied, $t,
                    [Windows.Graphics.Imaging.ExifOrientationMode]::IgnoreExifOrientation, [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])
      $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
      $lines += ($res.Lines | ForEach-Object { $_.Text })
    }
    return $lines
  } finally { $stream.Dispose() }
}

$root = (Resolve-Path $Folder).Path
if (-not $Out) { $Out = Join-Path (Split-Path $root -Parent) ((Split-Path $root -Leaf) + ".md") }
$images = Get-ChildItem -Path $root -Recurse -File | Where-Object { $_.Extension -match '^\.(png|jpe?g|bmp|gif|webp)$' } | Sort-Object FullName
$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine("# " + (Split-Path $root -Leaf) + " — 캡처 글자 인식 결과 (" + $images.Count + "장)")
[void]$sb.AppendLine("")
$i = 0; $fail = 0
foreach ($img in $images) {
  $i++
  $rel = $img.FullName.Substring($root.Length).TrimStart('\')
  [void]$sb.AppendLine("## " + $rel)
  try {
    $text = Read-Image $img.FullName
    if ($text.Count) { [void]$sb.AppendLine(($text -join "`n")) } else { [void]$sb.AppendLine("(글자 없음)") }
  } catch { $fail++; [void]$sb.AppendLine("(읽기 실패: " + $_.Exception.Message + ")") }
  [void]$sb.AppendLine("")
  if ($i % 20 -eq 0) { Write-Host "  $i / $($images.Count)" }
}
[System.IO.File]::WriteAllText($Out, $sb.ToString(), (New-Object System.Text.UTF8Encoding($false)))
Write-Host "완료: $($images.Count)장 (실패 $fail) → $Out"
