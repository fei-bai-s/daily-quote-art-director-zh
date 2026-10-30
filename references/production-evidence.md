# 生产证据与局部修订（schema 1.5；兼容1.4证据链）

**本文件的无字生成、双阶段冷审与本地排版命令只属于 `local_typesetting` 路线。**新记录默认图文一体，使用 [integrated-production.md](integrated-production.md)，不同时运行两套流程。历史缺少 `run.rendering_mode` 时仍按本文件回验；新建本地路线须显式选择。通用生成登记命令为两路线共用，但 `background` 字段在默认路线指带字原始卡片，不代表无字资产。

此文件只在生成、排版、审核登记或修订时读取。下列脚本把原有生产阶段的输入、版本和原始判断对应起来，不新增创作竞争。路径示例中的 `<skill-dir>`、`<run>` 必须替换为真实绝对路径；脚本输出的实际路径是后续输入，不能猜路径。

## 边界与依赖

- 新创作使用1.5；历史1.0–1.4保持原样，不把旧的通过值升级成新证据。1.5增加表达准入及独立表达判断，不增加生产阶段。仅修订旧卡字号可按原版本复查，须说明不代表已通过新版表达边界；要按1.5重新验收须另建修订、真实补审，不追认旧结果。
- 图像回读、确定性裁切和缩略图需要 Python Pillow；先确认 `python3 -c 'from PIL import Image'` 可用。缺失时使用环境已配置的依赖运行时，不以仅读PNG头替代完整解码。
- 正文、日期、出处、宜忌从记录读取；本地排版源负责准确渲染，生成模型只负责无字底图。
- 指纹用于防止过期结果或错误文件被沿用，不证明图文含义正确，也不是鉴定作者身份的签名系统。
- `production`、登记时间、文件指纹与审核输入快照由脚本生成。执行者只写真实创作决定与观察，不手填哈希，不虚构请求或审查者。

## 1. 生成请求与底图登记

完成选题、艺术锁与 pre 校验后，将本次实际要提交的完整提示词保存为文本，再登记请求：

```bash
python3 <skill-dir>/scripts/production_evidence.py <run>/design-record.json generation-start \
  --attempt-id A1 --prompt-file <run>/prompt-A1.txt --designer-context-id <实际创作者上下文ID>
```

然后使用 `imagegen`。工具成功返回后，保存可获得的原始返回文本／定位元数据（不是自己编写的成功说明），并登记实际结果：

```bash
python3 <skill-dir>/scripts/production_evidence.py <run>/design-record.json generation-complete \
  --attempt-id A1 --tool-result <run>/tool-result-A1.json \
  --tool-result-locator <实际工具调用或请求定位> --background <实际底图绝对路径>
python3 <skill-dir>/scripts/register_background.py <run>/design-record.json \
  --attempt-id A1 --background <实际底图绝对路径>
```

先登记开始，再调用，再登记完成；完成记录是返回后记录的时刻，实际工具时间有返回时保留在原始结果中。`registered_at` 另记，不把后来重新登记旧图的时间当成新生成时间。

同概念改提示词时新建 A2 等 attempt，并用 `--change-note` 说明执行层调整；不覆盖A1。更换语义重点或概念则返回相应层重新锁定，不能靠 change-note 豁免。底图失败不登记成成功，外发规则也不因有一个文件而满足。

常规生产可在 `generation-complete` 末尾加 `--select`，同一次命令完成结果登记与底图选用，不再单独调用 `register_background.py`。这不会自动通过执行检查；仍须实际看图并写 execution 结果。

看图后保存执行检查 JSON，填写真实结果：

```json
{
  "key_action_or_state_realized": "实际可见的关键结构／状态及缺口",
  "concept_fidelity": "与锁定概念的具体一致与偏差",
  "text_safe_area_usable": true,
  "background_text_free": true,
  "decision": "pass"
}
```

```bash
python3 <skill-dir>/scripts/production_evidence.py <run>/design-record.json execution --result <run>/execution.json
```

示例中的 true/pass 不是默认答案；失败用 `regenerate_same_concept`，概念问题返回概念层。脚本绑定的是实际审过的底图。

已填写真实 `layout` 数据时，可在 `execution` 末尾加 `--prepare-layout`，仅在执行检查通过后接续生成排版输入。任一步失败不写入主记录；可能留下的未引用中间文件不是通过证据。直接使用命令返回的路径，不为找路径再展开整份记录。

## 2. 确定性排版与版本登记

先填写 `layout` 的画布尺寸、日期、出处、宜忌，再运行：

```bash
python3 <skill-dir>/scripts/production_evidence.py <run>/design-record.json prepare-layout
```

脚本生成本轮无字排版底图、360px图和 `layout-request.json`。默认对已登记底图做居中 cover 裁切到目标画布，因此须先选择匹配的宽高比，回读裁切是否丢失关键关系；不可把生成器原图与另一种裁切的成品混作同一审查输入。若原图不适合这种裁切，调整画布或返回底图方案，不静默接受关键关系被切掉。

排版脚本读取实际 `layout-request.json` 中的 `base`、`text_data` 与画布尺寸，把文字叠加在该底图上，不能另换背景。渲染后由排版脚本计算并输出 manifest：

```json
{
  "text_data": {"quote_text":"核验原句","date_text":"YYYY-MM-DD","source_label":"作者《作品》","yi_text":"宜｜…","ji_text":"忌｜…"},
  "base_sha256": "从实际输入计算",
  "render_source_sha256": "从实际排版脚本计算",
  "final_sha256": "从实际PNG计算"
}
```

`text_data` 必须与输入逐字一致；换行属于排版，不能改变原句。星期必须与 `run.weekday` 相同，日期支持规范可识别形式；宜忌标签使用 `宜｜`、`忌｜`。示例只是数据合同，不是固定风格或布局模板。

排版源使用已设计好的显式行数组，并在渲染前断言 `''.join(quote_lines) == text_data['quote_text']`；不要用临时字符下标猜换行。字形宽度、边界仍须实际测量和看图。共用排版代码可以复用，坐标、字体和视觉构成不能作为默认模板继承。

```bash
python3 <skill-dir>/scripts/production_evidence.py <run>/design-record.json register-layout \
  --source <实际排版源> --final <最终PNG绝对路径> --manifest <实际manifest路径>
```

脚本完整解码、核对画布与输入版本，并产生有字360px图。设计源、底图或文字变更后必须登记新版本，不能沿用旧审核；用户输出文件仍使用新文件名，不覆盖历史成品。

## 3. 分阶段独立冷审

`prepare-layout` 完成、无字裁切已确认后，先创建不继承设计历史的独立审查上下文，再登记实际身份；无需等最终有字图渲染完毕：

```bash
python3 <skill-dir>/scripts/production_evidence.py <run>/design-record.json cold-start \
  --reviewer-id <实际审查者名称> --reviewer-context-id <实际独立上下文ID>
```

按返回的 `next_stage` 与 `input` 继续。新审查只把 `stage1-input.json`（含固定系列边界、不含当天方案）及其中两张匿名无字图交给审查者，不提供整份记录或允许其为理解任务读取设计目录；若字号修订满足继承条件并返回 stage2，直接使用已封存的第一阶段输出，不重做或覆盖它。审查者按合同返回原始 JSON：

```json
{
  "image_only_first_read": "第一眼实际可见的结构、状态或动作",
  "dominant_misreading": "最可能的另一种阅读",
  "uncertain_elements": "图中不能确定的方向、时间、因果或其他内容"
}
```

将审查者原始输出保存，不由创作者改写润色，再运行：

第一阶段观察期间主执行者可并行排版。审查者直接把原始 JSON 保存到指定独立文件，主执行者不要手抄内容。`cold-stage1` 登记前必须已执行 `register-layout`；否则拒绝生成第二阶段材料。脚本核对原无字图指纹、绑定最终有字图后才揭句。第一阶段结束早于排版时只保存原始文件并等待，不重复审核。若重新 `prepare-layout` 或改变裁切导致输入版本变化，遵循既有失效规则，不借并行沿用旧图观察。只改字号且已有可继承观察时，等新成品登记后直接走原 stage2 快路径，无需提前启动。

```bash
python3 <skill-dir>/scripts/production_evidence.py <run>/design-record.json cold-stage1 --result <原始stage1输出JSON>
```

脚本固定第一阶段输出后才生成第二阶段材料。把实际 `stage2-input.json` 给同一审查者，其中只追加原句、作者作品、必要原文语境和完整有字图，不含设计者解释。第二阶段合同：

```json
{
  "quote_meaning_in_own_words": "审查者根据原文形成的理解",
  "connection_assessment": "natural",
  "connection_reason": "可见关系如何与原句相容；没有呈现的部分与边界",
  "expression_review": {"mode":"relational_metaphor","figure_role":"none","decision":"pass","evidence":"指出实际画面通过何种关系转译，而非人物情节演示或空泛装饰。"},
  "readability": {
    "quote": {"full_resolution":"pass","evidence":"正文实际观察"},
    "source": {"full_resolution":"pass","evidence":"出处实际观察"},
    "yi": {"full_resolution":"pass","evidence":"宜项实际观察"},
    "ji": {"full_resolution":"pass","evidence":"忌项实际观察"}
  },
  "typography_design_review": {
    "reading_rhythm": "指出具体词组、换行或重读的实际效果",
    "image_text_relationship": "指出具体轴线、边界、体量或间隔如何支持阅读与图像",
    "hierarchy_and_breathing": "指出第一眼落点、接续路径及辅助信息的实际主次",
    "font_fit": "独立描述实际文字声音，给出字形／字重依据及与原句是否相容",
    "decision": "pass"
  },
  "decision": "pass"
}
```

1.5第二阶段输入还包含固定系列边界与本轮 `expression_policy`（只含用户原始例外，不含概念准入答案）。`expression_review` 分类及例外规则见艺术方向参考；即使连接为 natural，表达 fail 或违反默认边界仍登记为 revise，并阻止最终放行。1.4旧证据按旧合同回验，不能因此声称符合1.5审美。

连接判定允许 `natural/forced/conflicting/unrelated`，可读性为 `pass/fail`，结论为 `pass/revise`；如实选择，不默认照抄示例的通过值。日期、星期、原句与出处准确性另由最终校对负责。

本次更新后新生成的1.5第二阶段输入由脚本自动包含 `typography_review.profile=voice-layout-v1` 及四项固定问题，原始输出的 `typography_design_review` 不再是可省略的附加说明。不提供本轮声音预案、字体选择或小样胜出理由；直接使用返回的输入文件，不另开审核轮次。各项证据要求见排版参考，不能仅答“清楚”“有文学感”“留白充足”。有实质问题时排版及总体 `decision=revise`；即使误把总体填成 pass，脚本仍把排版 revise 登记为修订并拒绝最终放行。缺观察或无效结论拒绝登记。

此变更不修改 schema 和旧输入问题清单。已封存且没有此合同的1.4／1.5输入按原合同回验；旧记录未做过此审查，不能据回验成功追认。新的1.5排版修订生成新第二阶段输入时会携带新版合同，不要求重造未变的第一阶段观察。脚本检查字段、固定合同及版本绑定，具体审美是否成立仍须真实看图，非空文字不自动证明观察充分。

```bash
python3 <skill-dir>/scripts/production_evidence.py <run>/design-record.json cold-stage2 --result <原始stage2输出JSON>
```

登记通过不等于创作全链路完成。创作者再对照锁定方案与两阶段原始结果，填写 `semantic_cold_review.plan_vs_observed`、`missing_link`、`missing_link_note`、`explanation_required`：原文与编辑重点是否相容，关键机制是否确实出现，哪些只是设想。`alignment_basis` 由脚本自动绑定对应版本。不得修改独立原始输出让它同意设计者，也不能用 `natural` 掩盖概念所依赖的关键动作缺失或表达方式失败。

## 4. 局部修订与归档回验

- 保存新修订记录与新输出路径，保留旧记录和成品。对于1.4，重新准备排版会归档上一版本并清除旧交付状态；不是再次发送的授权。
- 只改字号／落位：内容、语义与底图不变就继承，不重跑选句或生成。新的 prepare-layout/register-layout 后，无字图指纹相同且由原审查上下文继续时，可继承原始第一阶段观察；有字图已变，第二阶段可读性必须重新审。若另换审查者，则在新的独立上下文中完成两阶段。
- 裁切或底图改变：无字审查输入改变，两阶段重新做；已经看过原句的上下文不能再充当新图的盲审者，必须创建新上下文。不要用相同文件名代替相同内容。
- 只刷新历史快照：内容与艺术决定不变，不使艺术锁或底图失效；若查出重复或需要冷却处理，则先回到内容判断，不能继续发送。
- 旧记录没有真实生成／盲审证据：可建立新修订、继承可核原文与历史线索，但不能通过填哈希、伪造请求来追认新标准。未补齐的部分明确保留为旧标准或待审；不擅自重生用户要求不变的底图。

最终理念从真实预案及成品对照写成四部分，文件与 `design_concept.full_text` 一致。完成其余实质检查并设置待验证的 `qa.final_status=passed` 后，生产放行：

```bash
python3 <skill-dir>/scripts/validate_record.py <run>/design-record.json --stage final
```

只有生产验证通过才可展示或按明确授权外发。`--archive` 用于只读回验当时的不可变历史快照，不要求当前系列未增长，但其结果不能当成新生产／新推送许可。旧版本验证不被报告为已通过1.4新增门槛。

生产时间戳由脚本以微秒精度记录，写理念时也用 `now_for_record` 取真实当前时间。并行只放宽“排版完成必须早于无字审核启动”的非必要顺序；排版完成和无字观察封存都必须早于揭句，最终理念仍在审核后。不得通过伪造时间或放宽未来时间校验规避错误。
