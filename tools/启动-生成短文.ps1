# =============================================================================
#  扇贝单词 · 今日短文生成（PowerShell 启动脚本）
#  用法：右键本文件 →「使用 PowerShell 运行」
#        或者在 PowerShell 里执行：  .\启动-生成短文.ps1
# =============================================================================

$ErrorActionPreference = "Continue"

# 切到脚本所在目录
Set-Location -Path $PSScriptRoot

# 优先用装了 Playwright 的 Python
$py = "D:\python\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  扇贝单词 · 今日短文生成" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. 打开扇贝网页版，自动翻页取回今日单词"
Write-Host "  2. 调用 DeepSeek 生成考研风格短文"
Write-Host "  3. 短文保存到  短文\  目录，并自动用 VS Code 打开"
Write-Host ""
Write-Host "  全程无需操作，大约 2~5 分钟。"
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# 执行主脚本
& $py "shanbay_daily_essay.py"
$code = $LASTEXITCODE

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
if ($code -eq 0) {
    Write-Host "  [完成] 短文已生成，可在 短文\ 目录查看。" -ForegroundColor Green
} else {
    Write-Host "  [失败] 运行出错（退出码 $code），请把上面的信息截图发给开发者。" -ForegroundColor Red
}
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""
Read-Host "按回车键关闭窗口"
