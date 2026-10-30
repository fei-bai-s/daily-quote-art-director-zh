# 图文一体生产与独立审核（schema 1.5）

默认 `run.rendering_mode=integrated_image_text`。内容与概念流程不变，生产将“无字生成＋本地加字”合并为一张带字卡片。给准确文案、已选画面概念及 [typography-production.md](typography-production.md) 的简短专业指引，字体、字号、落位、对齐、行数、字重、字色交给模型，不补具体排版参数。本文件替代本地生产参考，不叠加两套工作。

## 1. 锁定与生成

初始化默认图文一体。本轮全部文案保存在 `content.text`、`run.weekday` 和 `layout.date_text/source_label/yi_text/ji_text`；日期和星期匹配。`layout.canvas_width/height` 是绑定生成锁的画布目标，不是文字布局限制，不能事后改记录迁就模型尺寸。`layout.font_rationale/line_break_rationale` 可留空，不事后编造预先选型。`typography_direction` 保存本句声音／阅读需求，不把具体字体或落位写入提示词。用全部精确文案填入实际请求，要求不改字、不添加文案、no watermark，去掉 no text。

先完成历史、内容、作者及概念闸门，再 lock 和 pre 校验；文案或模式变化使锁失效。实际请求与工具返回依次登记：

```bash
python3 <skill-dir>/scripts/production_evidence.py <run>/design-record.json generation-start \
  --attempt-id A1 --prompt-file <实际提示词文件> --designer-context-id <实际上下文ID>
# 现在调用 imagegen，保存实际返回元数据；不得用自写成功声明替代。
python3 <skill-dir>/scripts/production_evidence.py <run>/design-record.json generation-complete \
  --attempt-id A1 --tool-result <工具原始返回文件> --tool-result-locator <实际调用定位> \
  --background <实际带字PNG> --select
```

兼容字段 `background`／`background_path` 在此路线指**原始带字卡片**，不能填无字证明。先开始、再调用、再完成；原件和指纹完整保存。执行闸门实际看图后保存原始JSON：

```json
{"key_action_or_state_realized":"真实可见的状态或关系", "concept_fidelity":"执行概念的具体情况", "text_safe_area_usable":true, "decision":"pass"}
```

`text_safe_area_usable` 在此指图文共存可用，不等于预先固定的空白块；不能填 `background_text_free=true`。执行失败用 `regenerate_same_concept`，不改观察凑通过。生成概念错误退回真正层级。

```bash
python3 <skill-dir>/scripts/production_evidence.py <run>/design-record.json execution --result <执行检查文件>
python3 <skill-dir>/scripts/production_evidence.py <run>/design-record.json register-integrated --final <新PNG绝对路径>
```

登记脚本复制原始PNG**原字节**，不裁切、不叠字、不修饰；生成360px预览，绑定准确文案。输出名不得覆盖历史。尺寸不符不能随手裁掉文字：返回生成修正或明确重新规划画布。`final_text_rendered_deterministically=false`，`generated_text_checked` 待独立逐字审查。禁止调用 prepare-layout/register-layout 搭配本路线。

## 2. 一次隔离上下文的完整卡片审核

使用不继承创作历史的真实独立上下文；可用 subagent 的无历史模式。无法隔离则停在待独立审核，不假填不同ID。工具输出只给 reviewer 读取其中真实 input 文件及图片，不给整份记录。图中已有文字，这不是无字盲审：`protocol=integrated_context_isolated`、`text_visible=true`、`quote_blind=false`。不人为移字或重生无字图追加假盲读。

```bash
python3 <skill-dir>/scripts/production_evidence.py <run>/design-record.json cold-start \
  --reviewer-id <真实审查者ID> --reviewer-context-id <独立上下文ID>
```

返回文件包含最终图、360px、六组准确文案、原作者作品与必要语境、固定表达边界和四项文字设计问题；不含提示词、锚点、概念、字体理由或设计理念。结果合同：

```json
{
  "actual_image_observation":"只描述实际可见关系，不用配文补造事件",
  "first_attention":"第一眼落点与后续阅读路径",
  "dominant_misreading":"最可能误读及其依据，没有也说明限度",
  "quote_meaning_in_own_words":"从原文自己解释",
  "connection_assessment":"natural",
  "connection_reason":"可见关系与句意相容的具体理由，区分文案推断",
  "expression_review":{"mode":"relational_metaphor","figure_role":"none","decision":"pass","evidence":"具体依据"},
  "typography_design_review":{"reading_rhythm":"具体词组／行","image_text_relationship":"具体轴线／体量／间隔","hierarchy_and_breathing":"具体区域和主次","font_fit":"实际字形与声音","decision":"pass"},
  "copy_check":{
    "quote":{"observed_text":"实际读到的正文","matches":true},
    "source":{"observed_text":"实际作者及完整作品／译者","matches":true},
    "yi":{"observed_text":"实际宜文案","matches":true},
    "ji":{"observed_text":"实际忌文案","matches":true},
    "date":{"observed_text":"实际日期","matches":true},
    "weekday":{"observed_text":"实际星期","matches":true}
  },
  "extra_text_absent":true,
  "readability":{
    "quote":{"full_resolution":"pass","evidence":"具体观察"},
    "source":{"full_resolution":"pass","evidence":"具体观察"},
    "yi":{"full_resolution":"pass","evidence":"具体观察"},
    "ji":{"full_resolution":"pass","evidence":"具体观察"},
    "date":{"full_resolution":"pass","evidence":"具体观察"},
    "weekday":{"full_resolution":"pass","evidence":"具体观察"}
  },
  "decision":"pass"
}
```

这里只是字段示例，不能复制通过值。与六组准确文案比对时只忽略空白／换行，字词和标点不改；不能把繁简转换、替字或译法变化当字体风格。读不清时记实际缺口，不能从 expected_copy 反抄假装看到了。

新初始化记录的输入还含 `meaning_grounding`：只提供来源定位、逐字上下文摘录及固定核验问题，不提供设计者的 `core_meaning/support_note/editorial_extension`。审查者先在现有 `quote_meaning_in_own_words` 中说明原文支持的含义、实际说话者、讨论对象和必要限制，再判断画面；不能从画面反推作者原意。句意依据不足或图像只承接新增生活劝告时 revise。此项复用一次独立审核，不增设解释竞赛，也不追改历史封存合同。

```bash
python3 <skill-dir>/scripts/production_evidence.py <run>/design-record.json cold-integrated --result <独立原始结果JSON>
```

直接登记未改写的审核文件。脚本即使看到总体 pass，也会因任何组不准确、表达失败、文字设计 revise 或连接不自然置为 revise。审美与语义判断仍需真实看图，脚本不执行OCR或证明评价正确。

## 3. 全链路复核、修正与交付

独立结果封存后，创作者重新对照**原句含义→编辑重点→视觉概念→实际可见关系**，填写 `plan_vs_observed`、`missing_link`、`missing_link_note`、`explanation_required`，不能只确认提示词物料出现。`missing_link=none`、`explanation_required=false` 仍是硬门槛；保留独立结果的 `alignment_basis`，不润色 reviewer 观察。

同锁同概念最多初版＋一次针对性编辑／重生，未完成／失败调用也计入。脚本拒绝第三次 generation-start，不能用 relock 同一方案、换 attempt 名或不登记失败绕过限制。修改必须登记新attempt、实际提示词、结果和新输出名，全部准确文案及受影响关系重审，使用新的独立上下文。仍失败停下说明缺口，请用户决定继续或切换本地路线；只有收到真实明确的继续指令，才可在额外单次 generation-start 加 `--retry-authorization <用户原话>`。每次超额调用各需授权，不由模型编写许可，不变成永久更大预算。不得为赶时间本地覆字。内容／概念改变返回对应阶段，而非累加提示词。

通过后写同一份四段式对外理念，与发送文件逐字一致。完成实际QA后设 `qa.final_status=passed`，再执行 `validate_record.py --stage final`；只有最终脚本也通过才展示／外发。本模块不授予企微、邮件或自动化配置修改权限。

历史无模式记录仍为本地路线；不就地补造新证据。路线变化另建修订并新锁。保持本地生产证据与旧合同可回验，不把默认变化追认为旧成图已走新方式。
