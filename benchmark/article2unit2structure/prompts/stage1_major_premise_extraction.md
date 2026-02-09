# Article→Unit→Structure（单次调用：st1 + st2 合并一次完成）

你需要在**一次**调用中完成参考的“两步流程”：

1) **Stage1（st1：法条→可执行单元 Unit）**：按参考 st1 prompt（下文原文）对 `rule_text` 做等价切分，得到 units。  
2) **Stage2（st2：Unit→Structure）**：对每个 unit 按参考 st2 prompt（下文原文，schema=st2.v3）做结构化，得到 st2.v3 JSON 对象。  

为了最大化可比性：下方直接嵌入了参考 st1 与 st2 的**定义与 few-shot 示例**（仅对“如何在一次调用里串联两步 + 最终输出格式”做最小包装说明）。

**最终输出格式（严格）**：

- 你最终只输出一个 JSON 数组，并用 `<final></final>` 包裹：`<final>[{...}, {...}, ...]</final>`。
- 数组里每个元素都是一个「Unit + Structure」配对对象，**字段固定**为：
  - `unit_id`：例如 `"U1"`/`"U2"`（从 `U1` 起连续编号）
  - `unit_text`：该 unit 的原文片段（来自 st1）
  - `unit_reason`：该 unit 用于检查什么（来自 st1）
  - `structure`：一个完整的 **st2.v3** 输出对象（字段/约束完全按 st2）
- 一致性硬约束（必须满足）：
  - `structure.unit_id/unit_text/unit_reason` 必须与外层 `unit_id/unit_text/unit_reason` **逐字符一致**
  - `structure.rule_id` 必须与输入 `rule_id` 一致（同条内所有 unit 的 `structure.rule_id` 相同）
- 数组顺序必须与 unit 在 `rule_text` 中出现顺序一致。

**特别说明（处理 st1/st2 文本中的 <final> 要求）**：

- 当下文 st1 prompt 要求输出 `<final>[...]</final>` 时：在本**单次调用**实验中，你只在**内部**生成该 units 数组；但这些 units 的 `unit/reason` 必须被你映射为最终输出的外层 `unit_text/unit_reason` 字段。
- 当下文 st2 prompt 要求输出 `<final>{...}</final>` 单个对象时：在本**单次调用**实验中，你对**每个 unit**生成一个独立的 st2.v3 对象，并把它放入最终输出里对应元素的 `structure` 字段。

**你收到的输入**：一个 JSON 对象（至少含 `rule_id/law_title/article_number/rule_text`，可能含 `full_article_text`）。

- 若输入未提供 `full_article_text`，则视为 `full_article_text = rule_text`（仅用于理解同条内指代；不得作为 effects 直接输出）。

**Stage2 组装输入（在你内部完成，不要显式输出）**：对每个 unit，你应当在脑中构造一个 st2 输入对象，字段与 st2 prompt 的“输入”一致：

- `unit_id`: 你从 `U1` 起连续编号
- `unit_text`: 来自 st1 的 `unit`
- `unit_reason`: 来自 st1 的 `reason`
- `all_units`: 由所有 `{unit_id, unit_text}` 组成的数组（便于 st2 做同条内指代理解）

---

## Few-shot（Unit + Structure Pairs）

下面给出两个 end-to-end 示例（仅用于说明“最终输出 schema”的形式）。示例中的 `structure` 均为 st2.v3 完整对象。

### 示例 1：1 个 unit

输入：

```json
{
  "rule_id": "moj_en_0f61035234::v_2020-05-21::Article14",
  "law_title": "外国企业常驻代表机构登记管理条例",
  "article_number": "14",
  "rule_text": "第十四条　代表机构可以从事与外国企业业务有关的下列活动：\n法律、行政法规或者国务院规定代表机构从事前款规定的业务活动须经批准的，应当取得批准。\n(一)与外国企业产品或者服务有关的市场调查、展示、宣传活动；\n(二)与外国企业产品销售、服务提供、境内采购、境内投资有关的联络活动。",
  "full_article_text": "第十四条　代表机构可以从事与外国企业业务有关的下列活动：\n(一)与外国企业产品或者服务有关的市场调查、展示、宣传活动；\n(二)与外国企业产品销售、服务提供、境内采购、境内投资有关的联络活动。\n法律、行政法规或者国务院规定代表机构从事前款规定的业务活动须经批准的，应当取得批准。"
}
```

输出（只输出 `<final>...</final>`，此处为示例展示）：

```xml
<final>
[
  {
    "unit_id": "U1",
    "unit_text": "第十四条　代表机构可以从事与外国企业业务有关的下列活动：\n法律、行政法规或者国务院规定代表机构从事前款规定的业务活动须经批准的，应当取得批准。\n(一)与外国企业产品或者服务有关的市场调查、展示、宣传活动；\n(二)与外国企业产品销售、服务提供、境内采购、境内投资有关的联络活动。",
    "unit_reason": "规定代表机构可以从事的与外国企业业务有关的具体活动，并规定如果法律、行政法规或者国务院要求批准，应当取得批准。",
    "structure": {
      "schema_version": "st2.v3",
      "rule_id": "moj_en_0f61035234::v_2020-05-21::Article14",
      "law_title": "外国企业常驻代表机构登记管理条例",
      "article_number": "14",
      "rule_text": "第十四条　代表机构可以从事与外国企业业务有关的下列活动：\n法律、行政法规或者国务院规定代表机构从事前款规定的业务活动须经批准的，应当取得批准。\n(一)与外国企业产品或者服务有关的市场调查、展示、宣传活动；\n(二)与外国企业产品销售、服务提供、境内采购、境内投资有关的联络活动。",
      "unit_id": "U1",
      "unit_text": "第十四条　代表机构可以从事与外国企业业务有关的下列活动：\n法律、行政法规或者国务院规定代表机构从事前款规定的业务活动须经批准的，应当取得批准。\n(一)与外国企业产品或者服务有关的市场调查、展示、宣传活动；\n(二)与外国企业产品销售、服务提供、境内采购、境内投资有关的联络活动。",
      "unit_reason": "规定代表机构可以从事的与外国企业业务有关的具体活动，并规定如果法律、行政法规或者国务院要求批准，应当取得批准。",
      "branches": [
        {
          "branch_id": "B1",
          "anchor": {
            "text": "代表机构可以从事与外国企业业务有关的下列活动：",
            "occurrence": 1
          },
          "norm_kind": "PERMISSION",
          "conditions": {
            "op": "AND",
            "items": [
              {
                "leaf_id": "B1.E1",
                "tag": "主体",
                "text": "代表机构"
              },
              {
                "leaf_id": "B1.E2",
                "tag": "前置条件",
                "text": "与外国企业业务有关的"
              },
              {
                "op": "OR",
                "items": [
                  {
                    "leaf_id": "B1.E3",
                    "tag": "行为",
                    "text": "(一)与外国企业产品或者服务有关的市场调查、展示、宣传活动；"
                  },
                  {
                    "leaf_id": "B1.E4",
                    "tag": "行为",
                    "text": "(二)与外国企业产品销售、服务提供、境内采购、境内投资有关的联络活动。"
                  }
                ]
              }
            ]
          },
          "effects": [
            {
              "effect_id": "B1.C1",
              "effect_text": "代表机构可以从事与外国企业业务有关的下列活动："
            }
          ],
          "depends_on_units": [],
          "depends_on_article_ref": [],
          "unresolved_reference": false,
          "notes": ""
        },
        {
          "branch_id": "B2",
          "anchor": {
            "text": "法律、行政法规或者国务院规定代表机构从事前款规定的业务活动须经批准的，应当取得批准。",
            "occurrence": 1
          },
          "norm_kind": "OBLIGATION",
          "conditions": {
            "op": "AND",
            "items": [
              {
                "leaf_id": "B2.E1",
                "tag": "主体",
                "text": "代表机构"
              },
              {
                "leaf_id": "B2.E2",
                "tag": "前置条件",
                "text": "法律、行政法规或者国务院规定代表机构从事前款规定的业务活动须经批准的"
              },
              {
                "op": "OR",
                "items": [
                  {
                    "leaf_id": "B2.E3",
                    "tag": "行为",
                    "text": "(一)与外国企业产品或者服务有关的市场调查、展示、宣传活动；"
                  },
                  {
                    "leaf_id": "B2.E4",
                    "tag": "行为",
                    "text": "(二)与外国企业产品销售、服务提供、境内采购、境内投资有关的联络活动。"
                  }
                ]
              }
            ]
          },
          "effects": [
            {
              "effect_id": "B2.C1",
              "effect_text": "应当取得批准。"
            }
          ],
          "depends_on_units": [],
          "depends_on_article_ref": [],
          "unresolved_reference": false,
          "notes": "inlined_intra_article_reference=true"
        }
      ],
      "meta": {
        "scope_policy": "unit_level_with_article_context",
        "compressed_enum": false,
        "unresolved_reference": false,
        "notes": ""
      }
    }
  }
]
</final>
```

### 示例 2：多个 unit

输入：

```json
{
  "rule_id": "moj_en_0f61035234::v_2020-05-21::Article19",
  "law_title": "外国企业常驻代表机构登记管理条例",
  "article_number": "19",
  "rule_text": "第十九条　任何单位和个人不得伪造、涂改、出租、出借、转让登记证和首席代表、代表的代表证(以下简称代表证)。\n登记证和代表证遗失或者毁坏的，代表机构应当在指定的媒体上声明作废，申请补领。\n登记机关依法作出准予变更登记、准予注销登记、撤销变更登记、吊销登记证决定的，代表机构原登记证和原首席代表、代表的代表证自动失效。",
  "full_article_text": "第十九条　任何单位和个人不得伪造、涂改、出租、出借、转让登记证和首席代表、代表的代表证(以下简称代表证)。\n登记证和代表证遗失或者毁坏的，代表机构应当在指定的媒体上声明作废，申请补领。\n登记机关依法作出准予变更登记、准予注销登记、撤销变更登记、吊销登记证决定的，代表机构原登记证和原首席代表、代表的代表证自动失效。"
}
```

输出（示例展示）：

```xml
<final>
[
  {
    "unit_id": "U1",
    "unit_text": "第十九条　任何单位和个人不得伪造、涂改、出租、出借、转让登记证和首席代表、代表的代表证(以下简称代表证)。\n",
    "unit_reason": "检查任何单位和个人是否遵守不得伪造、涂改、出租、出借、转让登记证和代表证的规定。",
    "structure": {
      "schema_version": "st2.v3",
      "rule_id": "moj_en_0f61035234::v_2020-05-21::Article19",
      "law_title": "外国企业常驻代表机构登记管理条例",
      "article_number": "19",
      "rule_text": "第十九条　任何单位和个人不得伪造、涂改、出租、出借、转让登记证和首席代表、代表的代表证(以下简称代表证)。\n登记证和代表证遗失或者毁坏的，代表机构应当在指定的媒体上声明作废，申请补领。\n登记机关依法作出准予变更登记、准予注销登记、撤销变更登记、吊销登记证决定的，代表机构原登记证和原首席代表、代表的代表证自动失效。",
      "unit_id": "U1",
      "unit_text": "第十九条　任何单位和个人不得伪造、涂改、出租、出借、转让登记证和首席代表、代表的代表证(以下简称代表证)。\n",
      "unit_reason": "检查任何单位和个人是否遵守不得伪造、涂改、出租、出借、转让登记证和代表证的规定。",
      "branches": [
        {
          "branch_id": "B1",
          "anchor": {
            "text": "不得伪造、涂改、出租、出借、转让登记证和首席代表、代表的代表证(以下简称代表证)。",
            "occurrence": 1
          },
          "norm_kind": "PROHIBITION",
          "conditions": {
            "op": "AND",
            "items": [
              {
                "leaf_id": "B1.E1",
                "tag": "主体",
                "text": "任何单位和个人"
              },
              {
                "op": "OR",
                "items": [
                  {
                    "leaf_id": "B1.E2",
                    "tag": "行为",
                    "text": "伪造"
                  },
                  {
                    "leaf_id": "B1.E3",
                    "tag": "行为",
                    "text": "涂改"
                  },
                  {
                    "leaf_id": "B1.E4",
                    "tag": "行为",
                    "text": "出租"
                  },
                  {
                    "leaf_id": "B1.E5",
                    "tag": "行为",
                    "text": "出借"
                  },
                  {
                    "leaf_id": "B1.E6",
                    "tag": "行为",
                    "text": "转让"
                  }
                ]
              },
              {
                "leaf_id": "B1.E7",
                "tag": "对象",
                "text": "登记证和首席代表、代表的代表证(以下简称代表证)"
              }
            ]
          },
          "effects": [
            {
              "effect_id": "B1.C1",
              "effect_text": "不得伪造、涂改、出租、出借、转让登记证和首席代表、代表的代表证(以下简称代表证)。"
            }
          ],
          "depends_on_units": [],
          "depends_on_article_ref": [],
          "unresolved_reference": false,
          "notes": ""
        }
      ],
      "meta": {
        "scope_policy": "unit_level_with_article_context",
        "compressed_enum": false,
        "unresolved_reference": false,
        "notes": ""
      }
    }
  },
  {
    "unit_id": "U2",
    "unit_text": "登记证和代表证遗失或者毁坏的，代表机构应当在指定的媒体上声明作废，申请补领。\n",
    "unit_reason": "检查登记证和代表证遗失或者毁坏时，代表机构是否在指定媒体上声明作废并申请补领。",
    "structure": {
      "schema_version": "st2.v3",
      "rule_id": "moj_en_0f61035234::v_2020-05-21::Article19",
      "law_title": "外国企业常驻代表机构登记管理条例",
      "article_number": "19",
      "rule_text": "第十九条　任何单位和个人不得伪造、涂改、出租、出借、转让登记证和首席代表、代表的代表证(以下简称代表证)。\n登记证和代表证遗失或者毁坏的，代表机构应当在指定的媒体上声明作废，申请补领。\n登记机关依法作出准予变更登记、准予注销登记、撤销变更登记、吊销登记证决定的，代表机构原登记证和原首席代表、代表的代表证自动失效。",
      "unit_id": "U2",
      "unit_text": "登记证和代表证遗失或者毁坏的，代表机构应当在指定的媒体上声明作废，申请补领。\n",
      "unit_reason": "检查登记证和代表证遗失或者毁坏时，代表机构是否在指定媒体上声明作废并申请补领。",
      "branches": [
        {
          "branch_id": "B1",
          "anchor": {
            "text": "代表机构应当在指定的媒体上声明作废，申请补领。",
            "occurrence": 1
          },
          "norm_kind": "OBLIGATION",
          "conditions": {
            "op": "AND",
            "items": [
              {
                "leaf_id": "B1.E1",
                "tag": "主体",
                "text": "代表机构"
              },
              {
                "leaf_id": "B1.E2",
                "tag": "前置条件",
                "text": "登记证和代表证遗失或者毁坏的"
              }
            ]
          },
          "effects": [
            {
              "effect_id": "B1.C1",
              "effect_text": "代表机构应当在指定的媒体上声明作废，申请补领。"
            }
          ],
          "depends_on_units": [],
          "depends_on_article_ref": [],
          "unresolved_reference": false,
          "notes": ""
        }
      ],
      "meta": {
        "scope_policy": "unit_level_with_article_context",
        "compressed_enum": false,
        "unresolved_reference": false,
        "notes": ""
      }
    }
  },
  {
    "unit_id": "U3",
    "unit_text": "登记机关依法作出准予变更登记、准予注销登记、撤销变更登记、吊销登记证决定的，代表机构原登记证和原首席代表、代表的代表证自动失效。",
    "unit_reason": "检查当登记机关作出准予变更登记、准予注销登记、撤销变更登记、吊销登记证决定时，代表机构原登记证和代表证是否自动失效。",
    "structure": {
      "schema_version": "st2.v3",
      "rule_id": "moj_en_0f61035234::v_2020-05-21::Article19",
      "law_title": "外国企业常驻代表机构登记管理条例",
      "article_number": "19",
      "rule_text": "第十九条　任何单位和个人不得伪造、涂改、出租、出借、转让登记证和首席代表、代表的代表证(以下简称代表证)。\n登记证和代表证遗失或者毁坏的，代表机构应当在指定的媒体上声明作废，申请补领。\n登记机关依法作出准予变更登记、准予注销登记、撤销变更登记、吊销登记证决定的，代表机构原登记证和原首席代表、代表的代表证自动失效。",
      "unit_id": "U3",
      "unit_text": "登记机关依法作出准予变更登记、准予注销登记、撤销变更登记、吊销登记证决定的，代表机构原登记证和原首席代表、代表的代表证自动失效。",
      "unit_reason": "检查当登记机关作出准予变更登记、准予注销登记、撤销变更登记、吊销登记证决定时，代表机构原登记证和代表证是否自动失效。",
      "branches": [
        {
          "branch_id": "B1",
          "anchor": {
            "text": "代表机构原登记证和原首席代表、代表的代表证自动失效。",
            "occurrence": 1
          },
          "norm_kind": "OTHER",
          "conditions": {
            "op": "AND",
            "items": [
              {
                "leaf_id": "B1.E1",
                "tag": "主体",
                "text": "代表机构"
              },
              {
                "leaf_id": "B1.E2",
                "tag": "前置条件",
                "text": "登记机关依法作出准予变更登记、准予注销登记、撤销变更登记、吊销登记证决定的"
              }
            ]
          },
          "effects": [
            {
              "effect_id": "B1.C1",
              "effect_text": "代表机构原登记证和原首席代表、代表的代表证自动失效。"
            }
          ],
          "depends_on_units": [],
          "depends_on_article_ref": [],
          "unresolved_reference": false,
          "notes": ""
        }
      ],
      "meta": {
        "scope_policy": "unit_level_with_article_context",
        "compressed_enum": false,
        "unresolved_reference": false,
        "notes": ""
      }
    }
  }
]
</final>
```

## 参考 st1 prompt（原文）

# 角色设定

你是一名**中文法条等价切分器**（Deterministic Statute Segmenter）。你的任务是把输入法条切分为若干段**与原文等价**的自然语言片段（unit），用于后续逐段检验（check）。本步骤只做“从法条到可执行检查单元”的切分，不做任何结构化改写、摘要、解释或语义压缩。

重要：你可以进行任意长度的思考；但你最终的回复必须放在 `<final></final>` 内部，且该标签内部只输出符合要求的 JSON，不要输出任何与答案无关的内容（包括解释、注释、markdown、标题、序号、空行、额外字段）。

# 任务目标

给定一段【本次切分目标文本】（通常是某条某款/某项的文本，主体仍然是该款/该项），并额外给出【整条法条上下文】辅助理解，输出一个 JSON 数组。数组中每个元素是一个字典，包含：
- `unit`：切分后的原文片段（尽可能与原文逐字符一致）
- `reason`：该片段用于检查什么（面向“检查点”描述，而非切分技术描述）

# 核心原则：最大化“逐字符等价”

1. 默认要求：`unit` 必须尽量**直接拷贝【本次切分目标文本】**，保持用词、语序、标点一致，优先做到**逐字符相等**。
2. 仅在必要时允许极小编辑：只有当原文存在跨句指代导致单段无法独立检验（例如“前款规定”“本条所称”）且不合并就会形成悬空检查点时，才允许通过“合并相邻句”来消除悬空；仍然应保持原文逐字逐句拼接，不得改写。
3. 禁止任何语义压缩：不得把“或者”改成“/”，不得同义替换，不得总结，不得把长句改短句，不得引入解释性词语。

# 全文上下文（重要）

你会同时看到：

- `FULL_ARTICLE_TEXT`：整条法条全文（上下文，仅用于理解“前款/前项/上述”等指代）；**不参与本次切分覆盖约束**。
- `TARGET_TEXT`：本次切分目标文本（通常是某条某款/某项的文本）；你的输出 units 必须**逐字符覆盖且只覆盖一次** `TARGET_TEXT`。

# 何时需要拆分、何时不拆分

你不是必须把每条法条都拆成多段：

- 如果法条不长，且整体只表达**同一个检查点/同一个规范命题**（例如同一个义务或同一个禁止，只是附带说明），可以只输出 1 个 `unit`（不拆分）。
- 只有当同一条法条中存在**多个可分离的检查点**时才拆分。典型情形包括但不限于：
  - 不同的规范动作：同时规定“应当核定”“应当通知”“应当履行”等多个动作；
  - 不同的规范性质：既有义务/禁止，也有责任后果（例如“未履行则赔偿/处罚”）；
  - 不同主体或不同对象的要求：对保险人、对被保险人/受益人、对第三方分别提出义务/禁止；
  - 程序性节点显著不同：受理请求→核定→通知→履行→逾期后果等。

# 切分规则（偏确定性，可复现）

1. 顺序规则：输出 `unit` 的顺序必须与原文出现顺序一致。
2. 覆盖规则：原文所有内容必须被覆盖且只覆盖一次（可合并但不得遗漏；不得重复覆盖）。
3. 单测规则：每个 `unit` 应尽量对应一个“可单测检查点”（一个义务/禁止/权利保障/责任后果/刑罚/程序节点）。
4. 时间/期限绑定规则：出现“及时”“在……内”“……日内”等期限要求时，不得把期限与其约束的动作拆开；期限必须留在同一个 `unit` 里。
5. 但书/例外绑定规则：出现“但……除外”“除非……”“合同另有约定的除外”等例外时，不得与其所修饰的规则拆开；例外必须留在同一个 `unit` 里。
6. 指代消解规则（关键）：出现“前款/前项/本款/本条”等指代且单独成段会悬空时，不得让其悬空；应与被指代的相邻规则合并为一个 `unit`，保证该 `unit` 可独立检验。合并时只允许把原文相邻句按原顺序拼接，不得改写。

# 输出格式（严格 JSON；稳定解析）

最终只输出一个 JSON 数组，形如：

```json
[
  {"unit": "……", "reason": "……"},
  {"unit": "……", "reason": "……"}
]
````

字段要求：

* `unit`：字符串；尽可能逐字符等于原文中的连续片段。
* `reason`：字符串；说明该 `unit` 在检验什么（例如：规定谁在什么条件下应当做什么；规定未履行的责任后果；规定什么刑罚或处罚；规定第三方不得做什么；规定权利保障等）。

  * `reason` 必须面向业务检验点；不要写“因为有多个动词所以拆分”这类切分技术理由。
  * `reason` 应简洁、明确、可用于生成测试断言（assertion）。

严禁：

* `<final>` 外输出任何内容。
* 输出非 JSON、输出多余字段、输出 markdown。
* 在 `unit` 中做语义压缩或同义替换。
* 增删法律要素（主体、条件、期限、例外、后果、刑罚等）。

# Few-shot 示例（严格复刻目标风格）

## 输入（法条原文）

第二十三条　保险人收到被保险人或者受益人的赔偿或者给付保险金的请求后，应当及时作出核定；情形复杂的，应当在三十日内作出核定，但合同另有约定的除外。保险人应当将核定结果通知被保险人或者受益人；对属于保险责任的，在与被保险人或者受益人达成赔偿或者给付保险金的协议后十日内，履行赔偿或者给付保险金义务。保险合同对赔偿或者给付保险金的期限有约定的，保险人应当按照约定履行赔偿或者给付保险金义务。
保险人未及时履行前款规定义务的，除支付保险金外，应当赔偿被保险人或者受益人因此受到的损失。
任何单位和个人不得非法干预保险人履行赔偿或者给付保险金的义务，也不得限制被保险人或者受益人取得保险金的权利。

## 输出（只示范最终 JSON）

<final>[
{
"unit": "保险人收到被保险人或者受益人的赔偿或者给付保险金的请求后，应当及时作出核定；情形复杂的，应当在三十日内作出核定，但合同另有约定的除外。",
"reason": "检查保险人收到被保险人或者受益人的赔偿或者给付保险金的请求后是否及时作出核定。"
},
{
"unit": "保险人应当将核定结果通知被保险人或者受益人；",
"reason": "检查保险人对被保险人或者受益人的通知义务，即应当将核定结果进行通知。"
},
{
"unit": "对属于保险责任的，在与被保险人或者受益人达成赔偿或者给付保险金的协议后十日内，履行赔偿或者给付保险金义务。保险合同对赔偿或者给付保险金的期限有约定的，保险人应当按照约定履行赔偿或者给付保险金义务。\n保险人未及时履行前款规定义务的，除支付保险金外，应当赔偿被保险人或者受益人因此受到的损失。",
"reason": "检查确认属于保险责任且保险人与被保险人或受益人达成赔偿或者给付保险金的协议后保险人是否及时履约"
},
{
"unit": "任何单位和个人不得非法干预保险人履行赔偿或者给付保险金的义务，也不得限制被保险人或者受益人取得保险金的权利。",
"reason": "确保保险人履行义务时不受干预"
}
]</final>

# 现在开始执行（单次调用：中间步骤，不要单独输出 stage1 的 <final>）

请对下方输入 JSON 对象中的 `rule_text` 进行等价切分，并按 st1 的规则在**内部**生成一个 units 数组（数组元素形如：`{"unit": "...", "reason": "..."}`）。

注意：本**单次调用**实验的最终输出不是 st1 的数组；你必须继续执行 Stage2。

在后续 Stage2 中：
- `unit_text` = st1 的 `unit`
- `unit_reason` = st1 的 `reason`
- `unit_id` 由你从 `U1` 起按顺序编号

FULL_ARTICLE_TEXT = 输入 JSON 的 `full_article_text`（若缺失则视为等于 `rule_text`）
TARGET_TEXT = 输入 JSON 的 `rule_text`


---

## 参考 st2 prompt（原文）

# st2_可执行单元到结构化

## 角色设定

你是一名**可执行单元结构化工程师**（Stage2 / st2，确定性编译器模式）。
你的任务是：在“本次目标文本（rule_text，通常是某条某款/某项文本）”作为一致性约束的前提下，额外参考“整条法条全文（full_article_text，上下文）”，只对**被分配的一个可执行单元（unit_text）**进行结构化，输出“可读 + 可编译 + 可检验”的结构化结果。

重要：你可以进行任意长度的思考；但你最终的回复必须放在 `<final></final>` 内部，且该标签内部只输出符合要求的 JSON；不要输出任何与答案无关的内容（包括解释、注释、markdown、标题、序号、空行、反引号、额外字段）。

## 为什么要做 st2

st1 的目标是把法条切成若干段与原文等价的 unit（逐段可单测）。
st2 的目标是把**一个 unit**变成结构化的“branches（独立规范分支）”，并为每个 branch 给出：

1. 可判定的条件树（conditions）
2. 原文可对齐的规范后果（effects）
3. 例外/但书（编译为互斥 branches + 排除条件）
4. 同法条内指代消解（内联）与跨法条引用（references）

## 输入

你会收到一个 JSON 对象，至少包含以下字段（字段名固定）：

* `rule_id`：字符串
* `law_title`：字符串（可能为空）
* `article_number`：字符串（可能为空）
* `rule_text`：字符串，本次目标文本原文（含标点与换行；通常为某条某款/某项；用于 echo 与对齐约束）
* `full_article_text`：字符串，整条法条原文（上下文，仅用于理解“前款/前项/上述”等指代；不得作为本次 unit 的 effects 直接输出）
* `unit_id`：字符串或数字（建议 "U1" / "U2" 或 1 / 2）
* `unit_text`：字符串，被分配的可执行单元原文片段（应来自 st1 输出，尽可能逐字符等于 rule_text 中的连续片段）
* `unit_reason`：字符串（st1 给出的该 unit 在检查什么的说明）

可选字段（若提供，可用于更确定地记录依赖，但仍不得处理非目标 unit）：

* `all_units`：数组，每个元素 `{ "unit_id": "...", "unit_text": "..." }`

### 输入一致性硬约束（必须满足）

你输出 JSON 中：

1. `rule_text` 必须与输入 `rule_text` **逐字符一致**（包括 `\n`、标点、空格）；不得删减、不得改写、不得重排。
2. `unit_text` 必须与输入 `unit_text` **逐字符一致**。

## 输出（Schema：以 branches 为核心）

你只能输出如下 JSON 结构（顶层键固定，禁止新增/改名）：

```json
{
  "schema_version": "st2.v3",
  "rule_id": "...",
  "law_title": "...",
  "article_number": "...",
  "rule_text": "...",
  "unit_id": "...",
  "unit_text": "...",
  "unit_reason": "...",
  "branches": [
    {
      "branch_id": "B1",
      "anchor": { "text": "...", "occurrence": 1 },
      "norm_kind": "OBLIGATION|PROHIBITION|PERMISSION|RIGHT|LIABILITY|SANCTION|DEFINITION|PROCEDURE|OTHER",
      "conditions": { "op": "AND|OR", "items": [ /* leaf or subtree */ ] },
      "effects": [
        { "effect_id": "B1.C1", "effect_text": "..." }
      ],
      "depends_on_units": ["U?"],
      "depends_on_article_ref": ["《法名》#第X条[#第Y款][#第Z项]"],
      "unresolved_reference": false,
      "notes": ""
    }
  ],
  "meta": {
    "scope_policy": "unit_level_with_article_context",
    "compressed_enum": false,
    "unresolved_reference": false,
    "notes": ""
  }
}
```

### leaf / subtree 的精确定义（conditions.items 里只能出现这两类）

1. leaf（叶子）

```json
{ "leaf_id": "B1.E1", "tag": "主体|行为|对象|前置条件|方式|目的|情节|数额|结果|程序|引用|排除", "text": "..." }
```

2. subtree（子树）

```json
{ "op": "AND|OR", "items": [ /* leaf or subtree */ ] }
```

### 输出硬约束（必须满足）

1. `branches` 必须按 **unit_text 中出现顺序**排列（用 anchor 在 unit_text 的首次出现位置排序）。
2. `branch_id` 必须从 `B1` 开始连续编号。
3. 每个 branch 的 leaf 必须从 `B{b}.E1` 起连续编号；effects 从 `B{b}.C1` 起连续编号。
4. `effects[].effect_text` 必须是 **unit_text 的连续子串**（逐字符一致），不得改写、不得概括、不得新增解释。
5. **不得输出 `exceptions` 字段**（顶层与 branch 内都不允许）。
6. `anchor.text` 必须是 **unit_text 的连续子串**；若该子串在 unit_text 中出现多次，用 `occurrence` 指明第几次（从 1 计数）。
7. `leaf.text` 的可对齐约束：

   * 对于 `tag = 引用`：**只用于“跨法条条文引用”**（例如“本法第十条”“依照第十条规定”“《××法》第十条第二款”）。
     - `leaf.text` 必须是 unit_text 中出现的**引用短语连续子串**；
     - 禁止把术语/名词短语当作引用（例如“负面清单”“本条所称…”不属于引用）；
     - 禁止用于同一法条内部指代（前款/前项/上述/该等）——这些必须在本 unit 内联展开（见第 7 节）。
   * 对于 `tag = 主体`：
     - 优先直接抽取 unit_text 中出现的主体短语（满足连续子串约束）；
     - 若 unit_text 中未明确出现主体短语，允许使用**最小占位主体**（如“行为人”），或从 rule_text 上下文中抽取最小主体短语；
     - 这类“占位/推断主体”允许不满足 unit_text 连续子串约束，但不得引入额外事实信息；并在 `notes` 中标记 `inferred_subject=true`。
   * 对于其他 `tag`：
     - 优先取 unit_text 的连续子串（逐字符一致）；
     - 仅当你在“同一法条内联展开指代”（第 7 节）时，允许 `leaf.text` 来自 full_article_text 的连续子串（逐字符一致），但不得改写与新增。
8. 除本 Schema 允许的键以外，禁止输出任何额外字段（包括顶层与分支内）。

## 核心概念与确定性规则

### 1) branch（独立规范分支）

branch = unit_text 内一条**独立可检验**的规范命题，通常以这些规范触发词为中心：
“应当/必须/不得/禁止/可以/有权/享有/视为/构成/应当承担/应当赔偿/处…/罚…/无效/不承担/不适用/应当通知/应当履行/在…内…”

一个 unit 通常对应 1 个 branch；但若 unit 为了消除指代悬空而合并了相邻句，可能包含多个检查点，此时必须拆成多个 branch（拆 branch 不改变 unit_text，只改变结构化结果）。

### 2) norm_kind（规范类型，必须给）

按 branch 的核心规范谓词确定：

* OBLIGATION：应当/必须/应…
* PROHIBITION：不得/禁止…
* PERMISSION：可以…（授权性）
* RIGHT：有权/享有…
* LIABILITY：应当承担/应当赔偿/除…外应当…
* SANCTION：处…/罚…/没收…/责令…
* DEFINITION：是指/包括/本条所称…
* PROCEDURE：程序性节点（受理→核定→通知→履行 等）
* OTHER：无法归类但仍为规范命题

### 3) conditions 与 effects 的边界（强约束）

* conditions：只放**可判定的事实前提/对象范围/程序状态/情节要素**。
* effects：只放**规范性后果**（应当/不得/可以/处罚/赔偿/无效/不承担等带来的“要求/禁止/授权/责任/制裁/程序动作”）。

注意：当原文用“未/不/未能/未及时 +（履行/通知/支付…）”描述**事实状态**作为责任触发条件时，允许该短语进入 conditions（因为它在逻辑上是前提而非后果），但必须原文拷贝且可对齐；对应的责任结论仍必须放入 effects。

**时间/期限约束放置规则（强制）**：

- 若 unit_text 中出现“在……内/于……前/期限届满/……日内”等，且它语义上约束的是某个规范动作（应当/不得/可以/履行/通知/作出决定等），则该时间短语必须与对应动作一起放在同一个 `effect_text` 内（保持原文连续子串）；不得仅把时间短语拆到 conditions 里。

### 4) “一般规则 + 特别情形” 的拆分与互斥（确定性）

若 unit_text 同时出现：

* 一般规则（如“应当及时…”）
* 特别情形规则（如“情形复杂的，应当在三十日内…”）

则必须拆成两个 branch，并按以下固定写法确保互斥：

* 一般规则 branch 的 conditions 中加入一个 `tag=排除` 的 leaf，`text` 取特别情形的触发短语（连续子串，如“情形复杂的”）。
* 特别情形 branch 的 conditions 中用 `tag=情节`（或更合适标签）写入该触发短语。
* 若 unit_text 里还包含例外/但书（如“但…除外”），不得输出 `exceptions` 字段；必须按“互斥 branches + 排除条件”的规则处理（见下文）。

`tag=排除` 只用于“为了互斥而拆分的分支边界”（包括：一般/特别情形边界、例外/但书边界），不得用于表达其他语义。

### 5) OR 的两类用法（确定性）

你必须区分两类 OR：

A. 分支 OR（branch-level）

* unit 内出现多个独立检查点 → 用多个 branch 表达（而不是把所有东西塞进一个 OR 大树）。
* `branches` 的存在本身就是“分支层”的表达方式。

B. 因子分解 OR（branch 内）

* 同一 branch 内出现“或者/或/之一/任一”等并列备选，且这些备选只在同一标签维度变化（常见：行为 或 对象）
* 写法：branch.conditions 采用 AND 外层，在其中放入一个 OR 子树
* OR 子树的每个子项必须是 leaf，且 `tag` 必须一致（全是 行为 或全是 对象 等）
* 禁止用“/”压缩并列选项

### 6) 例外/但书：去掉 exceptions，全用互斥 branches（强制）

出现这些模式必须“编译”为互斥 branches（并保持原文对齐）：
“但…除外/但是…/除外/不适用/另有约定的除外/除非…”

固定写法：

1) 主规则分支（main branch）
- 正常抽取条件与后果；
- 在 `conditions.items` 中追加一个 `tag=排除` 的 leaf，`text` 取例外触发短语（必须是 unit_text 连续子串），用于从结构上排除例外情形，保证互斥。

2) 例外分支（exception branch）
- `conditions` 中必须包含该例外触发短语（用 `tag=前置条件/排除/情节` 里更合适者；必须可对齐）；
- `effects`：
  - 若 unit_text 中存在“例外情形下的替代义务/替代后果”的原文连续子串，则抽取为 effect_text；
  - 若 unit_text 仅表达“除外/不适用”但没有明确替代后果，允许 `effects=[]`，并在 `notes` 中写明 `no_effect_due_to_exception_only`。

硬约束：

- 不得输出 `exceptions` 字段；
- 所有 branches 必须两两互斥（至少通过“主分支排除 + 例外分支触发条件”保证互斥）。

### 7) 指代消解与条文引用（非常关键）

你允许查看 full_article_text 来理解“本条/前款/前项/上述/该”等指代，但你只能结构化当前 unit。

处理规则（固定优先级）：

1) 同一法条内部指代（含跨 unit 的“前款/前项/该规定/上述”等）

* **必须内联展开**：从 `unit_text` / `full_article_text` /（若提供）`all_units` 中复制“最小必要的原文连续子串”，写入本 branch 的 conditions（用合适 tag）。
* 禁止输出 `tag=引用` 来记录这些“同法条内部指代”；也不需要填 `depends_on_units` / `depends_on_article_ref`（两者都置空）。
* branch.notes 可写 `inlined_intra_article_reference=true`（可选）。

2) 跨法条条文引用（引用对象不在本条 rule_text 内）

* 仅当 unit_text **显式出现条文号**（如“第十条/第十条第二款/第十条第（二）项”，或“《××法》第十条…”）时，才使用 `tag=引用`。
* 在 conditions 中用 `tag=引用` 记录 unit_text 中的引用短语（连续子串）。
* `depends_on_units`：本阶段暂不使用，固定输出 `[]`。
* `depends_on_article_ref`：写“规范化引用串”列表，格式固定为：

  * `《法名》#第X条[#第Y款][#第Z项]`
  * 若 unit_text 只写“本法/本条例…第X条”，则 `法名` 取输入 `law_title`；
  * 若 unit_text 自带“《…》”，则优先用 unit_text 的法名。
* unresolved_reference 判定（仅针对本项）：

  * 引用短语中能解析出明确条文号 → false
  * 引用短语只有“依照本法有关规定/另有规定”等无法落到条文号 → **不输出 tag=引用**（直接忽略该“泛引用”），或若必须保留则置 unresolved_reference=true 且 depends_on_article_ref 为空（尽量避免）

unit-level 的 `meta.unresolved_reference` 必须等于所有 branch 的 unresolved_reference 的 OR 聚合。

## 主体表达规则（建议，非强制）

- **不设置单独的 `subjects` 字段**（顶层与 branch 内都不需要）。
- 主体必须通过 `conditions.items` 中的 leaf 表达：`{ "tag": "主体", "text": "..." }`。
- 通常每个 branch 都应该包含 `tag=主体` 的 leaf（可通过 AND/OR 结构表达多个主体或主体备选）。
- 若 unit_text 没有直接写明主体：可使用“行为人”等最小占位主体，或从 rule_text 上下文抽取最小主体短语；但不得引入额外事实信息，并在 `notes` 标记 `inferred_subject=true`。
- 主体必须是名词性角色；不得把动宾短语当主体。

## 结构规范化与硬上限（防套娃）

必须满足：

* conditions 树最大深度 ≤ 6（从 branch.conditions 根到任一 leaf，AND/OR 算一层）
* 任一 AND/OR 节点 items 数量 ≤ 30
* 单个 branch 的 leaf 总数 ≤ 60；整个 unit 的 leaf 总数 ≤ 120

超限时按固定顺序收缩（直到不超限）：

1. 规范化：合并同类 AND/OR、删除单子节点 AND/OR、扁平化
2. 并列枚举过多（同一 tag 维度 ≥ 9）：用单一 leaf

   * `tag=行为` 或 `tag=对象`
   * `text="列举（按原文顺序：A、B、C、……）"`（若 unit_text 中没有“列举”原词也可用，但此时必须置 `meta.compressed_enum=true`，并在 meta.notes 标记 `compressed_enum=true`）
3. 完全重复 leaf 去重（同 tag + 同 text 只保留一次）
4. 仍超限：将最细的列举改为单一 leaf（仍用 `tag=行为/对象`），text 写 “见原文列举”，并置 `meta.compressed_enum=true`，`meta.notes` 标记 aggressive_compress=true

## 自检清单（输出前必须逐条通过）

Check-1 `rule_text` 与输入逐字符一致
Check-2 `unit_text` 与输入逐字符一致
Check-3 所有 effect_text/anchor.text 都可在 unit_text 中定位为连续子串
Check-4 `tag=引用` 的 leaf.text 必须能在 unit_text 中定位为连续子串；其余 leaf.text 优先能在 unit_text 中定位，若用于“同法条内联展开指代”则允许来自 full_article_text；若主体只能用占位“行为人”等，允许不对齐但需 notes 标记 inferred_subject=true
Check-5 branches 顺序与 unit_text 出现顺序一致；编号连续
Check-6 conditions 树深度≤6；无 AND→AND 单子节点、无 OR→OR 单子节点
Check-7 不得输出 exceptions；例外/但书已通过互斥 branches + 排除条件表达
Check-8 同法条内指代已内联展开；跨法条引用（若有）已记录 depends_on_article_ref 且 unresolved_reference 判定正确
Check-9 meta.unresolved_reference = OR(branch.unresolved_reference)


## Few-shot 示例（与 st2.v3 保持一致）

### Few-shot 1（保险法第二十三条 U1：一般规则 + 特别情形 + 例外（互斥 branches））

输入：

```json
{
  "rule_id": "中华人民共和国保险法|第二十三||",
  "law_title": "《中华人民共和国保险法》",
  "article_number": "第二十三条",
  "rule_text": "第二十三条　保险人收到被保险人或者受益人的赔偿或者给付保险金的请求后，应当及时作出核定；情形复杂的，应当在三十日内作出核定，但合同另有约定的除外。",
  "unit_id": "U1",
  "unit_text": "保险人收到被保险人或者受益人的赔偿或者给付保险金的请求后，应当及时作出核定；情形复杂的，应当在三十日内作出核定，但合同另有约定的除外。",
  "unit_reason": "检查保险人收到赔偿/给付请求后核定的期限要求及合同约定除外。"
}
```

期望输出：

<final>{
  "schema_version": "st2.v3",
  "rule_id": "中华人民共和国保险法|第二十三||",
  "law_title": "《中华人民共和国保险法》",
  "article_number": "第二十三条",
  "rule_text": "第二十三条　保险人收到被保险人或者受益人的赔偿或者给付保险金的请求后，应当及时作出核定；情形复杂的，应当在三十日内作出核定，但合同另有约定的除外。",
  "unit_id": "U1",
  "unit_text": "保险人收到被保险人或者受益人的赔偿或者给付保险金的请求后，应当及时作出核定；情形复杂的，应当在三十日内作出核定，但合同另有约定的除外。",
  "unit_reason": "检查保险人收到赔偿/给付请求后核定的期限要求及合同约定除外。",
  "branches": [
    {
      "branch_id": "B1",
      "anchor": { "text": "应当及时作出核定；", "occurrence": 1 },
      "norm_kind": "OBLIGATION",
      "conditions": {
        "op": "AND",
        "items": [
          { "leaf_id": "B1.E1", "tag": "主体", "text": "保险人" },
          { "leaf_id": "B1.E2", "tag": "前置条件", "text": "收到被保险人或者受益人的赔偿或者给付保险金的请求后" },
          { "leaf_id": "B1.E3", "tag": "排除", "text": "情形复杂的" }
        ]
      },
      "effects": [
        { "effect_id": "B1.C1", "effect_text": "应当及时作出核定；" }
      ],
      "depends_on_units": [],
      "depends_on_article_ref": [],
      "unresolved_reference": false,
      "notes": "general_rule_excludes_complex_case"
    },
    {
      "branch_id": "B2",
      "anchor": { "text": "情形复杂的，应当在三十日内作出核定", "occurrence": 1 },
      "norm_kind": "OBLIGATION",
      "conditions": {
        "op": "AND",
        "items": [
          { "leaf_id": "B2.E1", "tag": "主体", "text": "保险人" },
          { "leaf_id": "B2.E2", "tag": "前置条件", "text": "收到被保险人或者受益人的赔偿或者给付保险金的请求后" },
          { "leaf_id": "B2.E3", "tag": "情节", "text": "情形复杂的" },
          { "leaf_id": "B2.E4", "tag": "排除", "text": "但合同另有约定的除外" }
        ]
      },
      "effects": [
        { "effect_id": "B2.C1", "effect_text": "应当在三十日内作出核定" }
      ],
      "depends_on_units": [],
      "depends_on_article_ref": [],
      "unresolved_reference": false,
      "notes": "complex_case_excludes_contract_agreement_exception"
    },
    {
      "branch_id": "B3",
      "anchor": { "text": "但合同另有约定的除外", "occurrence": 1 },
      "norm_kind": "OTHER",
      "conditions": {
        "op": "AND",
        "items": [
          { "leaf_id": "B3.E1", "tag": "主体", "text": "保险人" },
          { "leaf_id": "B3.E2", "tag": "前置条件", "text": "但合同另有约定的除外" }
        ]
      },
      "effects": [],
      "depends_on_units": [],
      "depends_on_article_ref": [],
      "unresolved_reference": false,
      "notes": "no_effect_due_to_exception_only"
    }
  ],
  "meta": {
    "scope_policy": "unit_level_with_article_context",
    "compressed_enum": false,
    "unresolved_reference": false,
    "notes": ""
  }
}</final>

### Few-shot 2（保险法第二十三条 U2：通知义务）

输入：

```json
{
  "rule_id": "中华人民共和国保险法|第二十三||",
  "law_title": "《中华人民共和国保险法》",
  "article_number": "第二十三条",
  "rule_text": "保险人应当将核定结果通知被保险人或者受益人；",
  "unit_id": "U2",
  "unit_text": "保险人应当将核定结果通知被保险人或者受益人；",
  "unit_reason": "检查保险人通知核定结果的义务。"
}
```

期望输出：

<final>{
  "schema_version": "st2.v3",
  "rule_id": "中华人民共和国保险法|第二十三||",
  "law_title": "《中华人民共和国保险法》",
  "article_number": "第二十三条",
  "rule_text": "保险人应当将核定结果通知被保险人或者受益人；",
  "unit_id": "U2",
  "unit_text": "保险人应当将核定结果通知被保险人或者受益人；",
  "unit_reason": "检查保险人通知核定结果的义务。",
  "branches": [
    {
      "branch_id": "B1",
      "anchor": { "text": "应当将核定结果通知被保险人或者受益人；", "occurrence": 1 },
      "norm_kind": "OBLIGATION",
      "conditions": {
        "op": "AND",
        "items": [
          { "leaf_id": "B1.E1", "tag": "主体", "text": "保险人" }
        ]
      },
      "effects": [
        { "effect_id": "B1.C1", "effect_text": "应当将核定结果通知被保险人或者受益人；" }
      ],
      "depends_on_units": [],
      "depends_on_article_ref": [],
      "unresolved_reference": false,
      "notes": ""
    }
  ],
  "meta": {
    "scope_policy": "unit_level_with_article_context",
    "compressed_enum": false,
    "unresolved_reference": false,
    "notes": ""
  }
}</final>

### Few-shot 3（保险法第二十三条 U3：期限义务 + 合同约定优先 + 逾期责任）

输入：

```json
{
  "rule_id": "中华人民共和国保险法|第二十三||",
  "law_title": "《中华人民共和国保险法》",
  "article_number": "第二十三条",
  "rule_text": "对属于保险责任的，在与被保险人或者受益人达成赔偿或者给付保险金的协议后十日内，履行赔偿或者给付保险金义务。保险合同对赔偿或者给付保险金的期限有约定的，保险人应当按照约定履行赔偿或者给付保险金义务。\n保险人未及时履行前款规定义务的，除支付保险金外，应当赔偿被保险人或者受益人因此受到的损失。",
  "unit_id": "U3",
  "unit_text": "对属于保险责任的，在与被保险人或者受益人达成赔偿或者给付保险金的协议后十日内，履行赔偿或者给付保险金义务。保险合同对赔偿或者给付保险金的期限有约定的，保险人应当按照约定履行赔偿或者给付保险金义务。\n保险人未及时履行前款规定义务的，除支付保险金外，应当赔偿被保险人或者受益人因此受到的损失。",
  "unit_reason": "检查保险责任范围内的履行期限、合同约定优先及逾期责任。",
  "all_units": [
    { "unit_id": "U1", "unit_text": "保险人收到被保险人或者受益人的赔偿或者给付保险金的请求后，应当及时作出核定；情形复杂的，应当在三十日内作出核定，但合同另有约定的除外。" },
    { "unit_id": "U2", "unit_text": "保险人应当将核定结果通知被保险人或者受益人；" },
    { "unit_id": "U3", "unit_text": "对属于保险责任的，在与被保险人或者受益人达成赔偿或者给付保险金的协议后十日内，履行赔偿或者给付保险金义务。保险合同对赔偿或者给付保险金的期限有约定的，保险人应当按照约定履行赔偿或者给付保险金义务。\n保险人未及时履行前款规定义务的，除支付保险金外，应当赔偿被保险人或者受益人因此受到的损失。" }
  ]
}
```

期望输出：

<final>{
  "schema_version": "st2.v3",
  "rule_id": "中华人民共和国保险法|第二十三||",
  "law_title": "《中华人民共和国保险法》",
  "article_number": "第二十三条",
  "rule_text": "对属于保险责任的，在与被保险人或者受益人达成赔偿或者给付保险金的协议后十日内，履行赔偿或者给付保险金义务。保险合同对赔偿或者给付保险金的期限有约定的，保险人应当按照约定履行赔偿或者给付保险金义务。\n保险人未及时履行前款规定义务的，除支付保险金外，应当赔偿被保险人或者受益人因此受到的损失。",
  "unit_id": "U3",
  "unit_text": "对属于保险责任的，在与被保险人或者受益人达成赔偿或者给付保险金的协议后十日内，履行赔偿或者给付保险金义务。保险合同对赔偿或者给付保险金的期限有约定的，保险人应当按照约定履行赔偿或者给付保险金义务。\n保险人未及时履行前款规定义务的，除支付保险金外，应当赔偿被保险人或者受益人因此受到的损失。",
  "unit_reason": "检查保险责任范围内的履行期限、合同约定优先及逾期责任。",
  "branches": [
    {
      "branch_id": "B1",
      "anchor": { "text": "在与被保险人或者受益人达成赔偿或者给付保险金的协议后十日内，履行赔偿或者给付保险金义务。", "occurrence": 1 },
      "norm_kind": "OBLIGATION",
      "conditions": {
        "op": "AND",
        "items": [
          { "leaf_id": "B1.E1", "tag": "主体", "text": "保险人" },
          { "leaf_id": "B1.E2", "tag": "前置条件", "text": "对属于保险责任的" },
          { "leaf_id": "B1.E3", "tag": "前置条件", "text": "与被保险人或者受益人达成赔偿或者给付保险金的协议后" },
          { "leaf_id": "B1.E4", "tag": "排除", "text": "保险合同对赔偿或者给付保险金的期限有约定的" }
        ]
      },
      "effects": [
        { "effect_id": "B1.C1", "effect_text": "在与被保险人或者受益人达成赔偿或者给付保险金的协议后十日内，履行赔偿或者给付保险金义务。" }
      ],
      "depends_on_units": [],
      "depends_on_article_ref": [],
      "unresolved_reference": false,
      "notes": "default_deadline_excludes_contract_agreement_case"
    },
    {
      "branch_id": "B2",
      "anchor": { "text": "保险合同对赔偿或者给付保险金的期限有约定的", "occurrence": 1 },
      "norm_kind": "OBLIGATION",
      "conditions": {
        "op": "AND",
        "items": [
          { "leaf_id": "B2.E1", "tag": "主体", "text": "保险人" },
          { "leaf_id": "B2.E2", "tag": "前置条件", "text": "保险合同对赔偿或者给付保险金的期限有约定的" }
        ]
      },
      "effects": [
        { "effect_id": "B2.C1", "effect_text": "应当按照约定履行赔偿或者给付保险金义务。" }
      ],
      "depends_on_units": [],
      "depends_on_article_ref": [],
      "unresolved_reference": false,
      "notes": "contract_priority_rule"
    },
	    {
	      "branch_id": "B3",
	      "anchor": { "text": "保险人未及时履行前款规定义务的", "occurrence": 1 },
	      "norm_kind": "LIABILITY",
	      "conditions": {
	        "op": "AND",
	        "items": [
	          { "leaf_id": "B3.E1", "tag": "主体", "text": "保险人" },
	          { "leaf_id": "B3.E2", "tag": "前置条件", "text": "未及时履行前款规定义务的" },
	          {
	            "op": "OR",
	            "items": [
	              { "leaf_id": "B3.E3", "tag": "前置条件", "text": "在与被保险人或者受益人达成赔偿或者给付保险金的协议后十日内，履行赔偿或者给付保险金义务。" },
	              { "leaf_id": "B3.E4", "tag": "前置条件", "text": "应当按照约定履行赔偿或者给付保险金义务。" }
	            ]
	          }
	        ]
	      },
	      "effects": [
	        { "effect_id": "B3.C1", "effect_text": "除支付保险金外，应当赔偿被保险人或者受益人因此受到的损失。" }
	      ],
	      "depends_on_units": [],
	      "depends_on_article_ref": [],
	      "unresolved_reference": false,
	      "notes": "inlined_intra_article_reference=true"
	    }
	  ],
  "meta": {
    "scope_policy": "unit_level_with_article_context",
    "compressed_enum": false,
    "unresolved_reference": false,
    "notes": ""
  }
}</final>

### Few-shot 4（保险法第二十三条 U4：双禁止规范 -> 两个互斥 branches）

输入：

```json
{
  "rule_id": "中华人民共和国保险法|第二十三||",
  "law_title": "《中华人民共和国保险法》",
  "article_number": "第二十三条",
  "rule_text": "任何单位和个人不得非法干预保险人履行赔偿或者给付保险金的义务，也不得限制被保险人或者受益人取得保险金的权利。",
  "unit_id": "U4",
  "unit_text": "任何单位和个人不得非法干预保险人履行赔偿或者给付保险金的义务，也不得限制被保险人或者受益人取得保险金的权利。",
  "unit_reason": "确保保险人履行义务时不受干预。"
}
```

期望输出：

<final>{
  "schema_version": "st2.v3",
  "rule_id": "中华人民共和国保险法|第二十三||",
  "law_title": "《中华人民共和国保险法》",
  "article_number": "第二十三条",
  "rule_text": "任何单位和个人不得非法干预保险人履行赔偿或者给付保险金的义务，也不得限制被保险人或者受益人取得保险金的权利。",
  "unit_id": "U4",
  "unit_text": "任何单位和个人不得非法干预保险人履行赔偿或者给付保险金的义务，也不得限制被保险人或者受益人取得保险金的权利。",
  "unit_reason": "确保保险人履行义务时不受干预。",
  "branches": [
    {
      "branch_id": "B1",
      "anchor": { "text": "不得非法干预保险人履行赔偿或者给付保险金的义务", "occurrence": 1 },
      "norm_kind": "PROHIBITION",
      "conditions": {
        "op": "AND",
        "items": [
          { "leaf_id": "B1.E1", "tag": "主体", "text": "任何单位和个人" }
        ]
      },
      "effects": [
        { "effect_id": "B1.C1", "effect_text": "不得非法干预保险人履行赔偿或者给付保险金的义务" }
      ],
      "depends_on_units": [],
      "depends_on_article_ref": [],
      "unresolved_reference": false,
      "notes": ""
    },
    {
      "branch_id": "B2",
      "anchor": { "text": "也不得限制被保险人或者受益人取得保险金的权利。", "occurrence": 1 },
      "norm_kind": "PROHIBITION",
      "conditions": {
        "op": "AND",
        "items": [
          { "leaf_id": "B2.E1", "tag": "主体", "text": "任何单位和个人" }
        ]
      },
      "effects": [
        { "effect_id": "B2.C1", "effect_text": "也不得限制被保险人或者受益人取得保险金的权利。" }
      ],
      "depends_on_units": [],
      "depends_on_article_ref": [],
      "unresolved_reference": false,
      "notes": ""
    }
  ],
  "meta": {
    "scope_policy": "unit_level_with_article_context",
    "compressed_enum": false,
    "unresolved_reference": false,
    "notes": ""
  }
}</final>

### Few-shot 5（民法典：许可性规范）

输入：

```json
{
  "rule_id": "中华人民共和国民法典|五百六十二||",
  "law_title": "《中华人民共和国民法典》",
  "article_number": "第五百六十二条",
  "rule_text": "当事人可以约定一方解除合同的事由。解除合同的事由发生时，解除权人可以解除合同。",
  "unit_id": "U1",
  "unit_text": "当事人可以约定一方解除合同的事由。",
  "unit_reason": "检查当事人是否可以约定解除合同的事由。"
}
```

期望输出：

<final>{
  "schema_version": "st2.v3",
  "rule_id": "中华人民共和国民法典|五百六十二||",
  "law_title": "《中华人民共和国民法典》",
  "article_number": "第五百六十二条",
  "rule_text": "当事人可以约定一方解除合同的事由。解除合同的事由发生时，解除权人可以解除合同。",
  "unit_id": "U1",
  "unit_text": "当事人可以约定一方解除合同的事由。",
  "unit_reason": "检查当事人是否可以约定解除合同的事由。",
  "branches": [
    {
      "branch_id": "B1",
      "anchor": { "text": "可以约定一方解除合同的事由。", "occurrence": 1 },
      "norm_kind": "PERMISSION",
      "conditions": {
        "op": "AND",
        "items": [
          { "leaf_id": "B1.E1", "tag": "主体", "text": "当事人" }
        ]
      },
      "effects": [
        { "effect_id": "B1.C1", "effect_text": "可以约定一方解除合同的事由。" }
      ],
      "depends_on_units": [],
      "depends_on_article_ref": [],
      "unresolved_reference": false,
      "notes": ""
    }
  ],
  "meta": {
    "scope_policy": "unit_level_with_article_context",
    "compressed_enum": false,
    "unresolved_reference": false,
    "notes": ""
  }
}</final>

## 现在开始执行

请对下列输入 JSON 进行结构化。再次强调：你只能结构化 `unit_text` 对应的内容；可以参考 `full_article_text` 做指代判断与依赖记录，但不得把其他 unit 的规范内容输出为本次结构化结果的一部分。

输入 JSON 将以原样给出。

注意：这是参考 st2（单个 unit -> 单个 st2.v3 对象）的原始指令；但在本**单次调用**实验中，你最终必须输出 `<final>...</final>` 包裹的一个 JSON **数组**（每个元素是「Unit + Structure」配对对象，见本文开头的“最终输出格式（严格）”），而不是单个对象。st2 的“输出一个 JSON 对象”要求只适用于你在**内部**对每个 unit 生成 `structure` 时的中间结果。
