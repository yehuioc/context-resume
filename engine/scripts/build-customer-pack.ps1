param(
    [Parameter(Mandatory = $true)]
    [string]$InputJson,

    [Parameter(Mandatory = $true)]
    [string]$SourceManifestJson,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir,

    [switch]$HumanReviewConfirmed
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $InputJson -PathType Leaf)) {
    throw "Input JSON not found: $InputJson"
}
if (-not (Test-Path -LiteralPath $SourceManifestJson -PathType Leaf)) {
    throw "Source manifest JSON not found: $SourceManifestJson"
}
if (-not $HumanReviewConfirmed) {
    throw 'Human review confirmation is required. Review redaction, evidence sufficiency, conflicts, contribution boundaries, and source manifest before generating.'
}

$resolvedInput = [System.IO.Path]::GetFullPath($InputJson)
$resolvedSourceManifest = [System.IO.Path]::GetFullPath($SourceManifestJson)
$raw = [System.IO.File]::ReadAllText(
    $resolvedInput,
    [System.Text.UTF8Encoding]::new($false)
)
$sourceManifestRaw = [System.IO.File]::ReadAllText(
    $resolvedSourceManifest,
    [System.Text.UTF8Encoding]::new($false)
)

$sensitivePatterns = @(
    '(?<!\d)1[3-9]\d{9}(?!\d)',
    '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
    '(?i)(姓名|真实姓名|手机|手机号|电话|微信号?|wechat|qq号?|身份证|证件号|学号|详细地址|住址|账号|用户名|密码|验证码)\s*(是|为|[:：])\s*\S+',
    '(?<!\d)\d{17}[\dXx](?!\d)'
)

foreach ($pattern in $sensitivePatterns) {
    if ($raw -match $pattern -or $sourceManifestRaw -match $pattern) {
        throw "Potential personal information detected. Redact the JSON before generating a customer pack."
    }
}

$unsafeRequestPatterns = @(
    '(?i)(ignore|disregard)\s+(all\s+)?(previous|prior|system)\s+(instructions?|prompts?)',
    '(忽略|无视|绕过).{0,12}(此前|之前|系统|事实|证据).{0,8}(指令|规则|边界|要求)',
    '(请|帮我|要求|必须).{0,16}(编造|伪造|虚构|代投|登录.{0,6}账号|保证.{0,4}(面试|录用|offer|ATS))'
)

foreach ($pattern in $unsafeRequestPatterns) {
    if ($raw -match $pattern) {
        throw "Unsafe or out-of-scope request detected. Stop processing and review the source material."
    }
}

try {
    $data = $raw | ConvertFrom-Json
}
catch {
    throw "Input JSON is malformed: $($_.Exception.Message)"
}

try {
    $sourceManifest = $sourceManifestRaw | ConvertFrom-Json
}
catch {
    throw "Source manifest JSON is malformed: $($_.Exception.Message)"
}

$required = @(
    'customer_id',
    'generated_at',
    'target_role',
    'summary',
    'input_assessment',
    'evidence',
    'contribution_breakdown',
    'resume_bullets',
    'jd_matches',
    'interview_questions',
    'portfolio_outline',
    'warnings'
)

foreach ($field in $required) {
    $property = $data.PSObject.Properties[$field]
    $value = if ($null -eq $property) { $null } else { $property.Value }
    $isMissing = $null -eq $value
    $isBlankString = $value -is [string] -and [string]::IsNullOrWhiteSpace($value)
    if ($isMissing -or $isBlankString) {
        throw "Missing required field: $field"
    }
}

function Assert-ObjectFields {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Object,

        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string[]]$Fields
    )

    foreach ($field in $Fields) {
        $property = $Object.PSObject.Properties[$field]
        $value = if ($null -eq $property) { $null } else { $property.Value }
        if ($null -eq $value -or ($value -is [string] -and [string]::IsNullOrWhiteSpace($value))) {
            throw "Missing required field: $Path.$field"
        }
    }
}

if ([string]$data.customer_id -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$') {
    throw 'Invalid customer_id. Use an anonymous identifier containing only letters, numbers, dot, underscore, or hyphen.'
}

Assert-ObjectFields -Object $sourceManifest -Path 'source_manifest' -Fields @('customer_id', 'human_reviewed_at', 'sources')
if ([string]$sourceManifest.customer_id -ne [string]$data.customer_id) {
    throw 'Source manifest customer_id does not match input customer_id.'
}
if (@($sourceManifest.sources).Count -eq 0) {
    throw 'Missing required field: source_manifest.sources'
}

$sourceById = @{}
for ($index = 0; $index -lt @($sourceManifest.sources).Count; $index++) {
    $source = @($sourceManifest.sources)[$index]
    Assert-ObjectFields -Object $source -Path "source_manifest.sources[$index]" -Fields @('id', 'label', 'type', 'locator')
    $sourceId = [string]$source.id
    if ($sourceId -notmatch '^S[1-9]\d*$') {
        throw "Invalid source id at source_manifest.sources[$index]: $sourceId"
    }
    if ($sourceById.ContainsKey($sourceId)) {
        throw "Duplicate source id: $sourceId"
    }
    $sourceById[$sourceId] = $source
}

Assert-ObjectFields -Object $data.input_assessment -Path 'input_assessment' -Fields @(
    'pii_review',
    'evidence_sufficiency',
    'conflict_status',
    'target_jd_status',
    'request_scope'
)

$assessmentFailures = @()
if ($data.input_assessment.pii_review -ne 'passed') {
    $assessmentFailures += 'pii_review must be passed'
}
if ($data.input_assessment.evidence_sufficiency -ne 'sufficient') {
    $assessmentFailures += 'evidence_sufficiency must be sufficient'
}
if ($data.input_assessment.conflict_status -ne 'none') {
    $assessmentFailures += 'conflict_status must be none'
}
if ($data.input_assessment.target_jd_status -notin @('provided', 'not_provided')) {
    $assessmentFailures += 'target_jd_status must be provided or not_provided'
}
if ($data.input_assessment.request_scope -ne 'standard') {
    $assessmentFailures += 'request_scope must be standard'
}

$blockingReasons = @($data.input_assessment.blocking_reasons)
if ($blockingReasons.Count -gt 0) {
    $assessmentFailures += "blocking_reasons: $($blockingReasons -join '; ')"
}
if ($assessmentFailures.Count -gt 0) {
    throw "Generation blocked: $($assessmentFailures -join '; ')"
}

$requiredNonEmptyArrays = @(
    'evidence',
    'contribution_breakdown',
    'resume_bullets',
    'jd_matches',
    'interview_questions',
    'portfolio_outline',
    'warnings'
)
foreach ($field in $requiredNonEmptyArrays) {
    if (@($data.$field).Count -eq 0) {
        throw "Missing required field: $field"
    }
}

$evidenceById = @{}
for ($index = 0; $index -lt @($data.evidence).Count; $index++) {
    $item = @($data.evidence)[$index]
    Assert-ObjectFields -Object $item -Path "evidence[$index]" -Fields @('id', 'claim', 'source_refs', 'status', 'boundary')
    $id = [string]$item.id
    if ($id -notmatch '^E[1-9]\d*$') {
        throw "Invalid evidence id at evidence[$index]: $id"
    }
    if ($evidenceById.ContainsKey($id)) {
        throw "Duplicate evidence id: $id"
    }
    if ($item.status -notin @('confirmed', 'needs_confirmation')) {
        throw "Invalid evidence status for ${id}: $($item.status)"
    }
    $sourceRefs = @($item.source_refs)
    if ($sourceRefs.Count -eq 0) {
        throw "Missing required field: evidence[$index].source_refs"
    }
    foreach ($sourceRef in $sourceRefs) {
        if (-not $sourceById.ContainsKey([string]$sourceRef)) {
            throw "Unknown source reference at evidence[$index]: $sourceRef"
        }
    }
    $evidenceById[$id] = $item
}

function Assert-EvidenceReferences {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Item,

        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $refs = @($Item.evidence_refs)
    if ($refs.Count -eq 0) {
        throw "Missing required field: $Path.evidence_refs"
    }
    foreach ($ref in $refs) {
        if (-not $evidenceById.ContainsKey([string]$ref)) {
            throw "Unknown evidence reference at ${Path}: $ref"
        }
        if ($evidenceById[[string]$ref].status -ne 'confirmed') {
            throw "Unconfirmed evidence reference at ${Path}: $ref"
        }
    }
}

for ($index = 0; $index -lt @($data.contribution_breakdown).Count; $index++) {
    $item = @($data.contribution_breakdown)[$index]
    Assert-ObjectFields -Object $item -Path "contribution_breakdown[$index]" -Fields @(
        'actor',
        'contribution',
        'boundary',
        'evidence_refs'
    )
    Assert-EvidenceReferences -Item $item -Path "contribution_breakdown[$index]"
}

for ($index = 0; $index -lt @($data.resume_bullets).Count; $index++) {
    $item = @($data.resume_bullets)[$index]
    Assert-ObjectFields -Object $item -Path "resume_bullets[$index]" -Fields @('label', 'text', 'evidence_refs')
    Assert-EvidenceReferences -Item $item -Path "resume_bullets[$index]"
}

for ($index = 0; $index -lt @($data.jd_matches).Count; $index++) {
    Assert-ObjectFields -Object @($data.jd_matches)[$index] -Path "jd_matches[$index]" -Fields @(
        'requirement',
        'evidence',
        'status',
        'action'
    )
}

for ($index = 0; $index -lt @($data.portfolio_outline).Count; $index++) {
    Assert-ObjectFields -Object @($data.portfolio_outline)[$index] -Path "portfolio_outline[$index]" -Fields @(
        'section',
        'content'
    )
}

$resolvedOutput = [System.IO.Path]::GetFullPath($OutputDir)
[System.IO.Directory]::CreateDirectory($resolvedOutput) | Out-Null

function Escape-Html([object]$value) {
    return [System.Net.WebUtility]::HtmlEncode([string]$value)
}

function Escape-Markdown([object]$value) {
    $encoded = [System.Net.WebUtility]::HtmlEncode([string]$value)
    return $encoded.Replace('|', '\|')
}

function Get-SourceLabels([object]$sourceRefs) {
    return (@($sourceRefs) | ForEach-Object {
        $source = $sourceById[[string]$_]
        "$($_): $($source.label)"
    }) -join '; '
}

$md = [System.Text.StringBuilder]::new()
[void]$md.AppendLine("# 项目经历证据包")
[void]$md.AppendLine()
[void]$md.AppendLine("- 客户编号：``$(Escape-Markdown $data.customer_id)``")
[void]$md.AppendLine("- 生成日期：``$(Escape-Markdown $data.generated_at)``")
[void]$md.AppendLine("- 目标岗位：$(Escape-Markdown $data.target_role)")
[void]$md.AppendLine()
[void]$md.AppendLine("## 核心判断")
[void]$md.AppendLine()
[void]$md.AppendLine((Escape-Markdown $data.summary))
[void]$md.AppendLine()
[void]$md.AppendLine("## 事实与证据台账")
[void]$md.AppendLine()
[void]$md.AppendLine("| ID | 主张 | 来源 | 状态 | 表达边界 |")
[void]$md.AppendLine("| --- | --- | --- | --- | --- |")
foreach ($item in $data.evidence) {
    [void]$md.AppendLine("| $(Escape-Markdown $item.id) | $(Escape-Markdown $item.claim) | $(Escape-Markdown (Get-SourceLabels $item.source_refs)) | $(Escape-Markdown $item.status) | $(Escape-Markdown $item.boundary) |")
}
[void]$md.AppendLine()
[void]$md.AppendLine("## 贡献边界")
[void]$md.AppendLine()
[void]$md.AppendLine("| 参与方 | 已确认贡献 | 表达边界 | 证据 ID |")
[void]$md.AppendLine("| --- | --- | --- | --- |")
foreach ($item in $data.contribution_breakdown) {
    [void]$md.AppendLine("| $(Escape-Markdown $item.actor) | $(Escape-Markdown $item.contribution) | $(Escape-Markdown $item.boundary) | $(Escape-Markdown (@($item.evidence_refs) -join ', ')) |")
}
[void]$md.AppendLine()
[void]$md.AppendLine("## 简历表达")
foreach ($item in $data.resume_bullets) {
    [void]$md.AppendLine()
    [void]$md.AppendLine("### $(Escape-Markdown $item.label)")
    [void]$md.AppendLine()
    [void]$md.AppendLine("> $(Escape-Markdown $item.text)")
    [void]$md.AppendLine()
    [void]$md.AppendLine("证据：$(Escape-Markdown (@($item.evidence_refs) -join ', '))")
}
[void]$md.AppendLine()
[void]$md.AppendLine("## 目标岗位匹配")
[void]$md.AppendLine()
[void]$md.AppendLine("| 岗位要求 | 当前证据 | 状态 | 下一步 |")
[void]$md.AppendLine("| --- | --- | --- | --- |")
foreach ($item in $data.jd_matches) {
    [void]$md.AppendLine("| $(Escape-Markdown $item.requirement) | $(Escape-Markdown $item.evidence) | $(Escape-Markdown $item.status) | $(Escape-Markdown $item.action) |")
}
[void]$md.AppendLine()
[void]$md.AppendLine("## 面试追问")
[void]$md.AppendLine()
foreach ($item in $data.interview_questions) {
    [void]$md.AppendLine("- $(Escape-Markdown $item)")
}
[void]$md.AppendLine()
[void]$md.AppendLine("## 项目展示提纲")
foreach ($item in $data.portfolio_outline) {
    [void]$md.AppendLine()
    [void]$md.AppendLine("### $(Escape-Markdown $item.section)")
    [void]$md.AppendLine()
    [void]$md.AppendLine((Escape-Markdown $item.content))
}
[void]$md.AppendLine()
[void]$md.AppendLine("## 风险提示")
[void]$md.AppendLine()
foreach ($item in $data.warnings) {
    [void]$md.AppendLine("- $(Escape-Markdown $item)")
}

$mdPath = Join-Path $resolvedOutput '项目经历证据包.md'
[System.IO.File]::WriteAllText($mdPath, $md.ToString(), [System.Text.UTF8Encoding]::new($false))

$evidenceRows = ($data.evidence | ForEach-Object {
    "<tr><td>$(Escape-Html $_.id)</td><td>$(Escape-Html $_.claim)</td><td>$(Escape-Html (Get-SourceLabels $_.source_refs))</td><td>$(Escape-Html $_.status)</td><td>$(Escape-Html $_.boundary)</td></tr>"
}) -join "`n"
$contributionRows = ($data.contribution_breakdown | ForEach-Object {
    "<tr><td>$(Escape-Html $_.actor)</td><td>$(Escape-Html $_.contribution)</td><td>$(Escape-Html $_.boundary)</td><td>$(Escape-Html (@($_.evidence_refs) -join ', '))</td></tr>"
}) -join "`n"
$bulletCards = ($data.resume_bullets | ForEach-Object {
    "<article><h3>$(Escape-Html $_.label)</h3><p>$(Escape-Html $_.text)</p><small>证据：$(Escape-Html (@($_.evidence_refs) -join ', '))</small></article>"
}) -join "`n"
$jdRows = ($data.jd_matches | ForEach-Object {
    "<tr><td>$(Escape-Html $_.requirement)</td><td>$(Escape-Html $_.evidence)</td><td>$(Escape-Html $_.status)</td><td>$(Escape-Html $_.action)</td></tr>"
}) -join "`n"
$questionItems = ($data.interview_questions | ForEach-Object { "<li>$(Escape-Html $_)</li>" }) -join "`n"
$portfolioCards = ($data.portfolio_outline | ForEach-Object {
    "<article><h3>$(Escape-Html $_.section)</h3><p>$(Escape-Html $_.content)</p></article>"
}) -join "`n"
$warningItems = ($data.warnings | ForEach-Object { "<li>$(Escape-Html $_)</li>" }) -join "`n"

$html = @"
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>项目经历证据包</title>
<style>
:root{font-family:"Segoe UI","Microsoft YaHei",sans-serif;color:#172033;background:#f4f6f8}
body{margin:0;padding:32px}main{max-width:980px;margin:auto;background:white;padding:42px;border-radius:18px;box-shadow:0 16px 50px #17203318}
h1{font-size:36px;margin:0 0 8px}h2{margin-top:38px;border-bottom:2px solid #e7ebef;padding-bottom:10px}
.meta,.summary,article{background:#f7f9fb;border:1px solid #e2e7ec;border-radius:12px;padding:16px}.summary{font-size:18px;line-height:1.7}
table{width:100%;border-collapse:collapse}th,td{border:1px solid #dfe5ea;padding:10px;text-align:left;vertical-align:top}th{background:#eef2f5}
article{margin:12px 0}li{margin:8px 0;line-height:1.6}.warning{border-left:5px solid #dc7b34;background:#fff7ed;padding:14px 18px}
@media(max-width:720px){body{padding:12px}main{padding:22px}table{font-size:13px}h1{font-size:28px}}
</style>
</head>
<body><main>
<h1>项目经历证据包</h1>
<p class="meta">客户编号：$(Escape-Html $data.customer_id)｜生成日期：$(Escape-Html $data.generated_at)｜目标岗位：$(Escape-Html $data.target_role)</p>
<h2>核心判断</h2><p class="summary">$(Escape-Html $data.summary)</p>
<h2>事实与证据台账</h2><table><thead><tr><th>ID</th><th>主张</th><th>来源</th><th>状态</th><th>表达边界</th></tr></thead><tbody>$evidenceRows</tbody></table>
<h2>贡献边界</h2><table><thead><tr><th>参与方</th><th>已确认贡献</th><th>表达边界</th><th>证据 ID</th></tr></thead><tbody>$contributionRows</tbody></table>
<h2>简历表达</h2>$bulletCards
<h2>目标岗位匹配</h2><table><thead><tr><th>岗位要求</th><th>当前证据</th><th>状态</th><th>下一步</th></tr></thead><tbody>$jdRows</tbody></table>
<h2>面试追问</h2><ol>$questionItems</ol>
<h2>项目展示提纲</h2>$portfolioCards
<h2>风险提示</h2><div class="warning"><ul>$warningItems</ul></div>
</main></body></html>
"@

$htmlPath = Join-Path $resolvedOutput '项目经历证据包.html'
[System.IO.File]::WriteAllText($htmlPath, $html, [System.Text.UTF8Encoding]::new($false))

[pscustomobject]@{
    customer_id = [string]$data.customer_id
    markdown = $mdPath
    html = $htmlPath
} | ConvertTo-Json
