// Runs only after an explicit extension action, in Chrome's isolated world.
(() => {
  if (globalThis.__vozFormInstalled) return;
  globalThis.__vozFormInstalled = true;
  const supported = new Set([
    "text",
    "search",
    "email",
    "tel",
    "url",
    "number",
    "date",
    "time",
    "datetime-local",
    "month",
    "week",
    "textarea",
    "select",
    "checkbox",
    "radio",
  ]);
  const selector =
    "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image]),textarea,select,[role=radio],[role=checkbox]";
  let documentId = "";
  let pageUrl = "";
  let selectedForm = null;
  let sequence = 0;
  let references = new WeakMap();
  const replies = new Map();
  const normalized = (value) =>
    String(value || "")
      .normalize("NFD")
      .replace(/\p{Diacritic}/gu, "")
      .trim()
      .toLowerCase();
  const visible = (element) =>
    element.getClientRects().length > 0 &&
    getComputedStyle(element).visibility !== "hidden";
  const native = (element) => element.matches("input,textarea,select");
  const typeOf = (element) =>
    element.tagName === "INPUT"
      ? element.type
      : native(element)
        ? element.tagName.toLowerCase()
        : element.getAttribute("role");
  const checked = (element) =>
    native(element)
      ? element.checked
      : element.getAttribute("aria-checked") === "mixed"
        ? null
        : element.getAttribute("aria-checked") === "true";
  const accessibleLabel = (element) =>
    (element.getAttribute("aria-labelledby") || "")
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent?.trim())
      .filter(Boolean)
      .join(" ") ||
    element.getAttribute("aria-label") ||
    "";

  function reference(element) {
    if (!references.has(element)) {
      const uniqueId =
        element.id &&
        document.querySelectorAll(`[id="${CSS.escape(element.id)}"]`).length ===
          1;
      references.set(
        element,
        uniqueId ? element.id : `vf-${documentId}-${++sequence}`,
      );
    }
    return references.get(element);
  }

  function scope() {
    if (location.href !== pageUrl || !selectedForm?.isConnected)
      throw new Error(
        "A página mudou. Encerre a sessão e selecione a aba novamente.",
      );
    return selectedForm;
  }

  function controls() {
    const elements = [...scope().querySelectorAll(selector)].filter(
      (element) =>
        visible(element) &&
        // A custom wrapper around a visible native control is one field.
        (native(element) ||
          ![...element.querySelectorAll("input")].some(visible)),
    );
    if (elements.length > 200)
      throw new Error("Este formulário excede o limite de 200 campos.");
    if (
      elements.some(
        (element) =>
          !supported.has(typeOf(element)) && !element.matches(":disabled"),
      )
    ) {
      throw new Error(
        "Este formulário contém controles ainda não suportados, como senha ou envio de arquivos.",
      );
    }
    if (
      elements.some(
        (element) =>
          !native(element) &&
          ((element.matches("button") && element.type !== "button") ||
            element.matches("a[href]")),
      )
    )
      throw new Error(
        "Uma opção está associada a envio, limpeza ou navegação e não pode ser marcada pela extensão.",
      );
    if (
      elements.some(
        (element) =>
          !native(element) &&
          !["true", "false", "mixed"].includes(
            element.getAttribute("aria-checked"),
          ),
      )
    )
      throw new Error(
        "Uma opção não informa seu estado de seleção. Não foi possível inspecioná-la com segurança.",
      );
    return elements.filter((element) => supported.has(typeOf(element)));
  }

  function metadata(element) {
    const type = typeOf(element);
    const group = !native(element)
      ? element.closest(
          type === "radio" ? '[role="radiogroup"]' : '[role="group"]',
        )
      : null;
    const groupLabel = group ? accessibleLabel(group) : "";
    const optionLabel =
      accessibleLabel(element) ||
      element.labels?.[0]?.textContent?.trim() ||
      (!native(element) ? element.textContent?.trim() : "") ||
      element.placeholder ||
      element.name ||
      element.id ||
      "Campo sem rótulo";
    const label = groupLabel ? `${groupLabel}: ${optionLabel}` : optionLabel;
    const required = Boolean(
      element.required ||
      element.getAttribute("aria-required") === "true" ||
      group?.getAttribute("aria-required") === "true",
    );
    const selected = ["checkbox", "radio"].includes(type)
      ? checked(element)
      : element.value;
    const customValid =
      element.getAttribute("aria-invalid") === "true"
        ? false
        : !required ||
          (type === "radio" && group
            ? [...group.querySelectorAll('[role="radio"]')].some(
                (option) => checked(option) === true,
              )
            : selected === true);
    return {
      id: reference(element),
      name: element.name || (group ? reference(group) : null),
      label,
      type,
      role:
        type === "select"
          ? "combobox"
          : ["checkbox", "radio"].includes(type)
            ? type
            : "textbox",
      placeholder: element.placeholder || null,
      required,
      disabled: Boolean(
        element.matches(":disabled") ||
        element.closest('[aria-disabled="true"]'),
      ),
      readonly: Boolean(
        element.readOnly || element.getAttribute("aria-readonly") === "true",
      ),
      value: selected,
      valid: native(element)
        ? element.willValidate
          ? element.validity.valid
          : null
        : customValid,
      validation_message: element.validationMessage || "",
      ...(type === "select"
        ? {
            options: [...element.options].map((option) => ({
              label: option.label,
              value: option.value,
            })),
          }
        : {}),
    };
  }

  function inspect() {
    return {
      url: location.href,
      fields: controls().map(metadata),
      buttons: [],
    };
  }

  function find(query) {
    const wanted = normalized(query);
    if (!wanted) throw new Error("Informe o campo a preencher.");
    const scored = controls()
      .map((element) => {
        const meta = metadata(element);
        const values = [meta.label, meta.name, element.id, meta.placeholder]
          .filter(Boolean)
          .map(normalized);
        const score =
          wanted === normalized(meta.id)
            ? 10
            : values.includes(wanted)
              ? 3
              : wanted.length >= 3 &&
                  values.some((value) => value.includes(wanted))
                ? 1
                : 0;
        return { element, meta, score };
      })
      .filter((item) => item.score)
      .sort((a, b) => b.score - a.score);
    if (!scored.length) throw new Error(`Campo não encontrado: ${query}`);
    if (scored.length > 1 && scored[0].score === scored[1].score)
      throw new Error(`Campo ambíguo: ${query}`);
    return scored[0];
  }

  function read(query) {
    const { meta } = find(query);
    return {
      success: true,
      field: meta.label,
      field_ref: meta.id,
      value: meta.value,
      valid: meta.valid,
      validation_message: meta.validation_message,
    };
  }

  async function fill(query, value) {
    const { element, meta } = find(query);
    let expectedChecked = null;
    if (meta.disabled || meta.readonly)
      throw new Error("Este campo está desabilitado ou é somente leitura.");
    if (meta.type === "select" && element.multiple)
      throw new Error("Seleção múltipla ainda não é suportada.");
    if (["checkbox", "radio"].includes(meta.type)) {
      const yes = new Set(["true", "sim", "yes", "1", "aceito", "marcar"]);
      const no = new Set(["false", "nao", "no", "0"]);
      const wanted = normalized(value);
      if (!yes.has(wanted) && !no.has(wanted))
        throw new Error("Informe explicitamente se deseja marcar o campo.");
      expectedChecked = yes.has(wanted);
      if (checked(element) !== expectedChecked) {
        if (meta.type === "radio" && no.has(wanted))
          throw new Error(
            "Para trocar a opção, indique qual alternativa deseja marcar.",
          );
        element.click();
      }
    } else {
      let next = value;
      if (meta.type === "select") {
        const option = [...element.options].find((option) =>
          [normalized(option.label), normalized(option.value)].includes(
            normalized(value),
          ),
        );
        if (!option || option.disabled)
          throw new Error("Opção não encontrada ou indisponível.");
        next = option.value;
      }
      const prototype =
        meta.type === "textarea"
          ? HTMLTextAreaElement.prototype
          : meta.type === "select"
            ? HTMLSelectElement.prototype
            : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, "value").set.call(
        element,
        next,
      );
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
    }
    await new Promise((resolve) => setTimeout(resolve, 60));
    if (!element.isConnected || location.href !== pageUrl)
      throw new Error(
        "A página mudou durante o preenchimento. Confira o campo e reconecte a aba.",
      );
    const result = read(meta.id);
    if (expectedChecked !== null && result.value !== expectedChecked)
      throw new Error(
        "O clique não confirmou a seleção da opção. Confira o campo no site.",
      );
    return result;
  }

  async function execute(command) {
    if (command.document_id !== documentId || command.url !== location.href)
      throw new Error(
        "Esta sessão pertence a outra página. Selecione a aba novamente.",
      );
    if (command.name === "inspect_form") return inspect();
    if (command.name === "read_field") return read(command.arguments.field);
    if (command.name === "fill_field")
      return fill(command.arguments.field, command.arguments.value);
    throw new Error(
      "Operação não permitida. O envio deve ser feito por você no site.",
    );
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (sender.id !== chrome.runtime.id || message?.source !== "vozform")
      return;
    if (message.kind === "prepare") {
      try {
        const forms = [...document.forms].filter(visible);
        if (forms.length !== 1)
          throw new Error(
            "Selecione uma página com um único formulário HTML visível.",
          );
        documentId = crypto.randomUUID();
        pageUrl = location.href;
        selectedForm = forms[0];
        references = new WeakMap();
        sequence = 0;
        replies.clear();
        sendResponse({ success: true, document_id: documentId, ...inspect() });
      } catch (error) {
        sendResponse({ success: false, error: error.message });
      }
      return;
    }
    if (message.kind !== "command") return;
    const command = message.command;
    if (!replies.has(command.id)) {
      replies.set(
        command.id,
        execute(command).catch((error) => ({
          success: false,
          code: "BROWSER_ERROR",
          error: error.message,
        })),
      );
      if (replies.size > 256) replies.delete(replies.keys().next().value);
    }
    replies.get(command.id).then(sendResponse);
    return true;
  });
})();
