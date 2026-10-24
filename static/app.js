(() => {
  const state = {
    datasetId: null,
    dataset: null,
    recorder: null,
    stream: null,
    chunks: [],
    result: null,
    busy: false,
    activeApp: "data",
    codeBusy: false,
    codeMode: "GENERATION",
    authMode: "login",
  };

  const byId = (id) => document.getElementById(id);
  const fileInput = byId("dataset-file");
  const dropzone = byId("dropzone");
  const questionInput = byId("question");
  const analyzeButton = byId("analyze-button");
  const recordButton = byId("record-button");
  const uploadMessage = byId("upload-message");
  const analysisMessage = byId("analysis-message");
  const resultsPanel = byId("results-panel");
  const codeQuery = byId("code-query");
  const codeSubmit = byId("code-submit");

  function showLogin(message = "") {
    byId("login-screen").classList.remove("hidden");
    byId("assistant-chooser").classList.add("hidden");
    document.querySelector(".app-shell").classList.add("hidden");
    byId("login-password").value = "";
    byId("confirm-password").value = "";
    setAuthMode("login");
    if (message) showMessage(byId("login-message"), message, "error");
  }

  function setAuthMode(mode) {
    state.authMode = mode;
    const isRegistering = mode === "register";
    byId("login-title").firstChild.textContent = isRegistering ? "Create " : "Welcome ";
    byId("login-title").querySelector("span").textContent = isRegistering ? "account." : "back.";
    byId("login-description").textContent = isRegistering
      ? "Create an account to access your coding and data analysis assistants."
      : "Sign in to continue to your coding and data analysis assistants.";
    byId("login-password").title = "Use at least 6 characters.";
    byId("confirm-password-field").classList.toggle("hidden", !isRegistering);
    byId("confirm-password").required = isRegistering;
    byId("login-password").autocomplete = isRegistering ? "new-password" : "current-password";
    byId("login-submit").firstElementChild.textContent = isRegistering ? "Create account" : "Sign in";
    document.querySelectorAll("[data-auth-mode]").forEach((button) => {
      const active = button.dataset.authMode === mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    clearMessage(byId("login-message"));
  }

  function showChooser() {
    byId("login-screen").classList.add("hidden");
    byId("assistant-chooser").classList.remove("hidden");
    document.querySelector(".app-shell").classList.add("hidden");
  }

  function openWorkspace(appName) {
    byId("assistant-chooser").classList.add("hidden");
    document.querySelector(".app-shell").classList.remove("hidden");
    selectApp(appName);
  }

  async function initializeAuth() {
    try {
      const response = await fetch("/auth/session");
      if (!response.ok) throw new Error(await readError(response));
      const session = await response.json();
      if (session.authenticated) showChooser();
      else showLogin();
    } catch (error) {
      showLogin(`Could not check your session: ${error.message}`);
    }
  }

  function selectApp(appName) {
    state.activeApp = appName;
    document.querySelectorAll("[data-app-panel]").forEach((panel) => {
      panel.classList.toggle("hidden", panel.dataset.appPanel !== appName);
    });
    document.querySelectorAll("[data-app-tab]").forEach((button) => {
      const active = button.dataset.appTab === appName;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    const isCode = appName === "code";
    byId("breadcrumb-label").textContent = isCode ? "Code assistant" : "Data analysis";
    byId("workspace-title").textContent = isCode ? "Code workspace" : "Data workspace";
    byId("workspace-status").textContent = isCode
      ? "Ready for programming questions"
      : (state.dataset?.filename || "No dataset loaded");
    byId("data-pipeline").classList.toggle("hidden", isCode);
    byId("code-pipeline").classList.toggle("hidden", !isCode);
    byId("code-settings").classList.toggle("hidden", !isCode);
    byId("sidebar-note").innerHTML = isCode
      ? "Code help with web<br>references and citations."
      : "Your data stays local.<br>Queries run in read-only SQLite.";
  }

  function selectCodeMode(mode) {
    state.codeMode = mode;
    document.querySelectorAll("[data-code-mode]").forEach((button) => {
      const active = button.dataset.codeMode === mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    const isExplanation = mode === "EXPLANATION";
    byId("code-intro-title").textContent = isExplanation
      ? "What would you like to understand?"
      : "What are we building?";
    byId("code-intro-description").textContent = isExplanation
      ? "Ask about a programming concept, error, or code snippet."
      : "Describe the code or programming solution you need.";
    codeQuery.placeholder = isExplanation
      ? "e.g. Explain how Python decorators work..."
      : "e.g. Build a FastAPI endpoint that validates user feedback...";
  }

  function showMessage(element, text, kind = "info") {
    element.textContent = text;
    element.className = `message ${kind}`;
  }

  function clearMessage(element) {
    element.textContent = "";
    element.className = "message hidden";
  }

  function setBusy(isBusy, message = "") {
    state.busy = isBusy;
    document.body.classList.toggle("busy", isBusy);
    if (message) showMessage(analysisMessage, message);
    updateControls();
  }

  function updateControls() {
    const enabled = Boolean(state.datasetId) && !state.busy;
    questionInput.disabled = !enabled;
    analyzeButton.disabled = !enabled || !questionInput.value.trim();
    recordButton.disabled = !enabled || !navigator.mediaDevices?.getUserMedia;
    byId("audio-file").disabled = !enabled;
  }

  async function readError(response) {
    if (
      response.status === 401
      && !response.url.endsWith("/auth/login")
      && !response.url.endsWith("/auth/register")
    ) {
      showLogin("Your session has expired. Please sign in again.");
    }
    try {
      const body = await response.json();
      return body.detail || JSON.stringify(body);
    } catch {
      return `Request failed (${response.status}).`;
    }
  }

  function appendInlineMarkdown(element, text) {
    const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g;
    let lastIndex = 0;
    for (const match of text.matchAll(pattern)) {
      if (match.index > lastIndex) {
        element.append(document.createTextNode(text.slice(lastIndex, match.index)));
      }
      const token = match[0];
      let node;
      if (token.startsWith("**")) {
        node = document.createElement("strong");
        node.textContent = token.slice(2, -2);
      } else if (token.startsWith("`")) {
        node = document.createElement("code");
        node.textContent = token.slice(1, -1);
      } else {
        const link = token.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
        node = document.createElement("a");
        node.href = link[2];
        node.target = "_blank";
        node.rel = "noopener noreferrer";
        node.textContent = link[1];
      }
      element.append(node);
      lastIndex = match.index + token.length;
    }
    if (lastIndex < text.length) {
      element.append(document.createTextNode(text.slice(lastIndex)));
    }
  }

  function renderAnswerMarkdown(element, markdown) {
    const lines = markdown
      .replace(/```[\w+-]*\s*\n[\s\S]*?```/g, "")
      .trim()
      .split("\n");
    let paragraph = [];
    let list = null;
    const flushParagraph = () => {
      if (!paragraph.length) return;
      const block = document.createElement("p");
      appendInlineMarkdown(block, paragraph.join(" "));
      element.append(block);
      paragraph = [];
    };
    const closeList = () => {
      if (list) {
        element.append(list);
        list = null;
      }
    };

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        flushParagraph();
        closeList();
        continue;
      }
      const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
      if (heading) {
        flushParagraph();
        closeList();
        const block = document.createElement(heading[1].length === 1 ? "h2" : "h3");
        appendInlineMarkdown(block, heading[2]);
        element.append(block);
        continue;
      }
      const numberedItem = trimmed.match(/^\d+[.)]\s+(.+)$/);
      if (numberedItem) {
        flushParagraph();
        if (!list || list.tagName !== "OL") {
          closeList();
          list = document.createElement("ol");
        }
        const listItem = document.createElement("li");
        appendInlineMarkdown(listItem, numberedItem[1]);
        list.append(listItem);
        continue;
      }
      const item = trimmed.match(/^[-*]\s+(.+)$/);
      if (item) {
        flushParagraph();
        if (!list || list.tagName !== "UL") {
          closeList();
          list = document.createElement("ul");
        }
        const listItem = document.createElement("li");
        appendInlineMarkdown(listItem, item[1]);
        list.append(listItem);
        continue;
      }
      closeList();
      paragraph.push(trimmed);
    }
    flushParagraph();
    closeList();
  }

  function renderPythonCode(codeElement, source) {
    const keywords = new Set([
      "and", "as", "assert", "async", "await", "break", "class", "continue",
      "def", "del", "elif", "else", "except", "False", "finally", "for",
      "from", "global", "if", "import", "in", "is", "lambda", "None",
      "nonlocal", "not", "or", "pass", "raise", "return", "True", "try",
      "while", "with", "yield",
    ]);
    const builtins = new Set([
      "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
      "int", "len", "list", "map", "max", "min", "open", "print", "range",
      "set", "str", "sum", "super", "tuple", "type", "zip",
    ]);
    const lines = source.split("\n");
    let multilineString = null;

    lines.forEach((line, lineIndex) => {
      const lineElement = document.createElement("span");
      lineElement.className = "code-line";
      const number = document.createElement("span");
      number.className = "line-number";
      number.textContent = String(lineIndex + 1);
      const sourceElement = document.createElement("span");
      sourceElement.className = "code-line-source";
      lineElement.append(number, sourceElement);

      const appendToken = (className, token) => {
        if (!token) return;
        if (!className) {
          sourceElement.append(document.createTextNode(token));
          return;
        }
        const highlighted = document.createElement("span");
        highlighted.className = className;
        highlighted.textContent = token;
        sourceElement.append(highlighted);
      };

      let index = 0;
      while (index < line.length) {
        if (multilineString) {
          const closingIndex = line.indexOf(multilineString, index);
          const end = closingIndex === -1 ? line.length : closingIndex + multilineString.length;
          appendToken("code-string", line.slice(index, end));
          index = end;
          if (closingIndex !== -1) multilineString = null;
          continue;
        }

        const rest = line.slice(index);
        const whitespace = rest.match(/^\s+/);
        if (whitespace) {
          appendToken("", whitespace[0]);
          index += whitespace[0].length;
          continue;
        }
        if (rest.startsWith("#")) {
          appendToken("code-comment", rest);
          break;
        }

        const stringStart = rest.match(/^(?:[rRuUbBfF]{1,2})?("""|'''|"|')/);
        if (stringStart) {
          const prefixAndQuote = stringStart[0];
          const delimiter = stringStart[1];
          const contentStart = index + prefixAndQuote.length;
          const closingIndex = line.indexOf(delimiter, contentStart);
          const end = closingIndex === -1
            ? line.length
            : closingIndex + delimiter.length;
          appendToken("code-string", line.slice(index, end));
          index = end;
          if (closingIndex === -1 && delimiter.length === 3) {
            multilineString = delimiter;
          }
          continue;
        }

        const word = rest.match(/^[A-Za-z_]\w*/);
        if (word) {
          let className = "";
          if (keywords.has(word[0])) className = "code-keyword";
          else if (builtins.has(word[0])) className = "code-builtin";
          else if (/^\s*\(/.test(line.slice(index + word[0].length))) {
            className = "code-function";
          }
          appendToken(className, word[0]);
          index += word[0].length;
          continue;
        }

        const numberToken = rest.match(/^(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?/i);
        if (numberToken) {
          appendToken("code-number", numberToken[0]);
          index += numberToken[0].length;
          continue;
        }
        appendToken("", line[index]);
        index += 1;
      }
      codeElement.append(lineElement);
    });
  }

  function withoutExpectedOutput(markdown) {
    return markdown.replace(
      /^#{1,3}\s*expected output\s*$\s*[\s\S]*?(?=^#{1,3}\s+|(?![\s\S]))/im,
      "",
    ).trim();
  }

  function generationOverview(markdown) {
    return withoutExpectedOutput(markdown)
      .replace(/^#{1,3}\s*references\s*$\s*[\s\S]*?(?=^#{1,3}\s+|(?![\s\S]))/im, "")
      .replace(/```[\w+-]*\s*\n[\s\S]*?```/g, "")
      .trim();
  }

  function renderExplanation(result, originalText) {
    const answer = document.createElement("div");
    answer.className = "chat-bubble assistant-answer explanation-answer";
    renderAnswerMarkdown(answer, result.answer || originalText);
    return answer;
  }

  function addTraceAndDocuments(container, result) {
    if (result.trace?.length) {
      const details = document.createElement("details");
      details.className = "code-trace";
      const summary = document.createElement("summary");
      summary.textContent = "🧭 Pipeline trace";
      const list = document.createElement("div");
      list.className = "trace-items";
      for (const event of result.trace) {
        const item = document.createElement("div");
        item.className = `trace-item ${event.status || "info"}`;
        item.textContent = `${event.step} — ${event.details}`;
        list.append(item);
      }
      details.append(summary, list);
      container.append(details);
    }

    if (result.documents?.length) {
      const details = document.createElement("details");
      details.className = "retrieved-documents";
      const summary = document.createElement("summary");
      summary.textContent = `📚 Retrieved examples (${result.documents.length})`;
      details.append(summary);
      for (const [index, documentInfo] of result.documents.entries()) {
        const article = document.createElement("article");
        article.className = "retrieved-document";
        const label = document.createElement("strong");
        label.textContent = `Example ${index + 1} — ${documentInfo.id}`;
        const code = document.createElement("pre");
        code.textContent = documentInfo.content.slice(0, 4000);
        article.append(label, code);
        details.append(article);
      }
      container.append(details);
    }
  }

  function addCodeOperations(container, prompt, result, messageId) {
    if (result.intent !== "GENERATION" || !result.code) return;
    const operations = document.createElement("section");
    operations.className = "code-operations";
    const heading = document.createElement("div");
    heading.className = "code-operation-heading";
    heading.textContent = "VALIDATE · EXECUTE · SAVE";

    const controls = document.createElement("div");
    controls.className = "code-operation-controls";
    const approvalLabel = document.createElement("label");
    const approval = document.createElement("input");
    approval.type = "checkbox";
    approval.id = `code-approval-${messageId}`;
    const approvalText = document.createElement("span");
    approvalText.textContent = "I reviewed this code and approve running it locally";
    approvalLabel.append(approval, approvalText);

    const validateButton = document.createElement("button");
    validateButton.type = "button";
    validateButton.textContent = "Run basic validation";
    const executeButton = document.createElement("button");
    executeButton.type = "button";
    executeButton.textContent = "Execute code";
    executeButton.disabled = true;
    approval.addEventListener("change", () => {
      executeButton.disabled = !approval.checked;
    });

    const status = document.createElement("div");
    status.className = "operation-status";
    const output = document.createElement("pre");
    output.className = "operation-output hidden";
    validateButton.addEventListener("click", async () => {
      if (!approval.checked) {
        status.className = "operation-status error";
        status.textContent = "Review the code and check the approval box first. Validation executes the code.";
        return;
      }
      await runCodeAction("/assistant/validate", {
        code: result.code,
        approved: approval.checked,
      }, status, output, validateButton);
    });
    executeButton.addEventListener("click", async () => {
      await runCodeAction("/assistant/execute", {
        code: result.code,
        approved: approval.checked,
        timeout: 5,
      }, status, output, executeButton);
    });
    controls.append(approvalLabel, validateButton, executeButton);
    operations.append(heading, controls, status, output);

    if (result.needs_reference_solution) {
      const form = document.createElement("form");
      form.className = "reference-form";
      const title = document.createElement("strong");
      title.textContent = "🧠 Add a reference solution";
      const note = document.createElement("p");
      note.textContent = "Provide a Python solution to improve personal retrieval. It will be executed for basic validation and saved only after both approvals. Execution is not sandboxed.";
      const taskLabel = document.createElement("label");
      taskLabel.textContent = "Task description";
      const taskInput = document.createElement("input");
      taskInput.type = "text";
      taskInput.maxLength = 10000;
      taskInput.required = true;
      taskInput.value = prompt;
      taskInput.className = "reference-task";
      taskInput.setAttribute("aria-label", "Task description");
      taskLabel.append(taskInput);
      const codeInput = document.createElement("textarea");
      codeInput.required = true;
      codeInput.value = result.code;
      codeInput.setAttribute("aria-label", "Reference Python solution");
      const saveApprovalLabel = document.createElement("label");
      const saveApproval = document.createElement("input");
      saveApproval.type = "checkbox";
      saveApproval.required = true;
      const saveApprovalText = document.createElement("span");
      saveApprovalText.textContent = "I approve saving this reference solution if basic validation passes.";
      saveApprovalLabel.append(saveApproval, saveApprovalText);
      const submit = document.createElement("button");
      submit.type = "submit";
      submit.textContent = "Validate and save reference";
      const formStatus = document.createElement("div");
      formStatus.className = "operation-status";

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!approval.checked) {
          formStatus.className = "operation-status error";
          formStatus.textContent = "Review the reference code and confirm execution before saving.";
          return;
        }
        await runCodeAction("/assistant/reference-solutions", {
          task: taskInput.value,
          code: codeInput.value,
          language: "python",
          approved: approval.checked,
          save_approved: saveApproval.checked,
        }, formStatus, null, submit);
      });
      form.append(title, note, taskLabel, codeInput, saveApprovalLabel, submit, formStatus);
      operations.append(form);
    }
    container.append(operations);
  }

  async function runCodeAction(endpoint, payload, status, output, button) {
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "Working…";
    status.className = "operation-status";
    status.textContent = "";
    if (output) output.classList.add("hidden");
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || `Request failed (${response.status}).`);
      if (result.validation) {
        status.textContent = `${result.validation.reason}${result.saved ? `\nSaved reference solution: ${result.solution_id}` : ""}`;
        status.className = `operation-status ${result.validation.valid ? "success" : "error"}`;
        if (result.validation.stdout && output) {
          output.textContent = `Standard output:\n${result.validation.stdout}`;
          output.classList.remove("hidden");
        }
        return;
      }
      const success = Object.hasOwn(result, "valid")
        ? result.valid
        : Boolean(result.success);
      const message = result.reason || (success ? "Process completed successfully." : "Process failed.");
      status.className = `operation-status ${success ? "success" : "error"}`;
      status.textContent = message;
      const logs = [
        result.stdout ? `Standard output:\n${result.stdout}` : "",
        result.stderr ? `Standard error:\n${result.stderr}` : "",
      ].filter(Boolean).join("\n\n");
      if (logs && output) {
        output.textContent = logs;
        output.classList.remove("hidden");
      }
    } catch (error) {
      status.className = "operation-status error";
      status.textContent = error.message;
    } finally {
      button.textContent = originalText;
      button.disabled = false;
    }
  }

  let nextMessageId = 1;
  function appendChatMessage(role, text, result = null) {
    const messageId = nextMessageId++;
    const article = document.createElement("article");
    article.className = `chat-message ${role === "user" ? "user-message" : "assistant-message"}`;
    const avatar = document.createElement("span");
    avatar.className = "chat-avatar";
    avatar.textContent = role === "user" ? "Y" : "C";
    const content = document.createElement("div");
    content.className = "chat-content";

    if (role === "user") {
      content.className = "chat-bubble";
      content.textContent = text;
    } else if (result?.intent === "EXPLANATION") {
      content.append(renderExplanation(result, text));
    } else {
      const answer = document.createElement("div");
      const isGeneration = result?.intent === "GENERATION";
      answer.className = `chat-bubble assistant-answer${isGeneration ? " code-overview" : ""}`;
      renderAnswerMarkdown(
        answer,
        (isGeneration ? generationOverview(text) : text.replace(/```[\w+-]*\s*\n[\s\S]*?```/g, "").trim()) || text,
      );
      content.append(answer);

      if (result?.code) {
        const codeWrapper = document.createElement("div");
        codeWrapper.className = "generated-code";
        const heading = document.createElement("div");
        heading.className = "generated-code-heading";
        const codeTitle = document.createElement("span");
        codeTitle.className = "generated-code-title";
        codeTitle.textContent = "▤";
        const language = document.createElement("span");
        language.textContent = "GENERATED CODE";
        const copy = document.createElement("button");
        copy.type = "button";
        copy.className = "copy-code";
        copy.textContent = "Copy";
        copy.addEventListener("click", async () => {
          try {
            await navigator.clipboard.writeText(result.code);
            copy.textContent = "Copied";
            window.setTimeout(() => { copy.textContent = "Copy"; }, 1500);
          } catch {
            copy.textContent = "Copy unavailable";
          }
        });
        const headingLabel = document.createElement("div");
        headingLabel.className = "generated-code-label";
        headingLabel.append(codeTitle, language);
        heading.append(headingLabel, copy);
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        renderPythonCode(code, result.code);
        pre.append(code);
        codeWrapper.append(heading, pre);
        content.append(codeWrapper);
      }

      if (result?.intent === "GENERATION" && result.expected_output) {
        const expectedOutput = document.createElement("section");
        expectedOutput.className = "expected-output";
        const title = document.createElement("strong");
        title.textContent = "Expected output · illustrative, not executed";
        const output = document.createElement("pre");
        output.textContent = result.expected_output;
        expectedOutput.append(title, output);
        content.append(expectedOutput);
      }

      if (result?.references?.length) {
        const references = document.createElement("div");
        references.className = "code-references";
        const title = document.createElement("strong");
        title.textContent = "References";
        references.append(title);
        const list = document.createElement("ol");
        for (const reference of result.references) {
          const item = document.createElement("li");
          const link = document.createElement("a");
          link.href = reference.url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = reference.title;
          item.append(link);
          list.append(item);
        }
        references.append(list);
        content.append(references);
      } else if (result?.intent === "GENERATION") {
        const references = document.createElement("div");
        references.className = "code-references";
        references.textContent = "No web references were returned for this response.";
        content.append(references);
      }
      addCodeOperations(content, result?.query || "", result, messageId);
      addTraceAndDocuments(content, result || {});
    }

    article.append(avatar, content);
    byId("code-chat").append(article);
    article.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function askCodeAssistant(query) {
    const prompt = query.trim();
    if (!prompt || state.codeBusy) return;
    clearMessage(byId("code-message"));
    appendChatMessage("user", prompt);
    codeQuery.value = "";
    state.codeBusy = true;
    codeSubmit.disabled = true;

    const loading = document.createElement("article");
    loading.className = "chat-message assistant-message loading-message";
    loading.innerHTML = '<span class="chat-avatar">C</span><div class="chat-bubble">Thinking, searching, and preparing your answer…</div>';
    byId("code-chat").append(loading);
    loading.scrollIntoView({ behavior: "smooth", block: "nearest" });

    try {
      const response = await fetch("/assistant/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: prompt,
          top_k: Number(byId("top-k").value),
          mode: state.codeMode,
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const result = await response.json();
      loading.remove();
      result.query = prompt;
      appendChatMessage("assistant", result.answer || "The assistant returned an empty response.", result);
    } catch (error) {
      loading.remove();
      showMessage(byId("code-message"), error.message, "error");
    } finally {
      state.codeBusy = false;
      codeSubmit.disabled = !codeQuery.value.trim();
    }
  }

  async function uploadDataset(file) {
    clearMessage(uploadMessage);
    if (!file || !file.name.toLowerCase().endsWith(".csv")) {
      showMessage(uploadMessage, "Choose a .csv file.", "error");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    byId("upload-panel").classList.add("busy");
    showMessage(uploadMessage, "Uploading and preparing your dataset...");

    try {
      const response = await fetch("/datasets/upload", { method: "POST", body: formData });
      if (!response.ok) throw new Error(await readError(response));
      const dataset = await response.json();
      state.datasetId = dataset.dataset_id;
      state.dataset = dataset;

      if (state.activeApp === "data") byId("workspace-status").textContent = file.name;
      byId("dataset-chip").textContent = `${dataset.row_count.toLocaleString()} rows`;
      byId("dataset-chip").classList.add("ready");
      byId("dataset-card").innerHTML = "";
      const details = document.createElement("div");
      const name = document.createElement("div");
      name.className = "dataset-name";
      name.textContent = dataset.filename;
      const meta = document.createElement("div");
      meta.className = "dataset-meta";
      meta.textContent = `${dataset.row_count.toLocaleString()} rows · ${dataset.columns.length} columns · ${dataset.columns.map((column) => column.name).join(", ")}`;
      details.append(name, meta);
      const ready = document.createElement("span");
      ready.className = "status-dot";
      byId("dataset-card").append(details, ready);
      byId("dataset-card").classList.remove("hidden");
      clearMessage(uploadMessage);
      updateControls();
      questionInput.focus();
    } catch (error) {
      showMessage(uploadMessage, error.message, "error");
    } finally {
      byId("upload-panel").classList.remove("busy");
    }
  }

  function renderResult(result, source) {
    state.result = result;
    byId("result-question").textContent = result.question;
    byId("result-source").textContent = source === "voice" ? "VOICE ANALYSIS" : "TEXT ANALYSIS";
    byId("result-explanation").textContent = result.explanation;
    byId("result-sql").textContent = result.sql;
    byId("sql-reason").textContent = result.sql_reason || "";
    byId("result-count").textContent = `${result.results.row_count.toLocaleString()} row${result.results.row_count === 1 ? "" : "s"}`;
    byId("truncated-note").classList.toggle("hidden", !result.results.truncated);

    const transcript = byId("transcript-block");
    if (result.transcript) {
      transcript.textContent = `Heard: “${result.transcript}”`;
      transcript.classList.remove("hidden");
    } else {
      transcript.textContent = "";
      transcript.classList.add("hidden");
    }

    const columns = result.results.columns;
    const table = document.createElement("table");
    const head = document.createElement("thead");
    const headerRow = document.createElement("tr");
    for (const column of columns) {
      const th = document.createElement("th");
      th.textContent = column;
      headerRow.append(th);
    }
    head.append(headerRow);
    const body = document.createElement("tbody");
    for (const row of result.results.rows) {
      const tr = document.createElement("tr");
      for (const column of columns) {
        const td = document.createElement("td");
        td.textContent = row[column] === null ? "—" : String(row[column]);
        td.title = td.textContent;
        tr.append(td);
      }
      body.append(tr);
    }
    if (!result.results.rows.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = Math.max(columns.length, 1);
      td.textContent = "No rows matched this question.";
      tr.append(td);
      body.append(tr);
    }
    table.append(head, body);
    const wrapper = byId("result-table-wrap");
    wrapper.replaceChildren(table);
    resultsPanel.classList.remove("hidden");
    resultsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function analyzeText(question, source = "text") {
    if (!state.datasetId) {
      showMessage(analysisMessage, "Upload a CSV dataset before asking a question.", "error");
      return;
    }
    if (!question.trim()) {
      showMessage(analysisMessage, "Enter or record a question first.", "error");
      return;
    }

    clearMessage(analysisMessage);
    resultsPanel.classList.add("hidden");
    setBusy(true, "Generating SQL, running a safe query, and preparing your answer...");

    try {
      const response = await fetch(`/datasets/${encodeURIComponent(state.datasetId)}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim() }),
      });
      if (!response.ok) throw new Error(await readError(response));
      renderResult(await response.json(), source);
      clearMessage(analysisMessage);
    } catch (error) {
      showMessage(analysisMessage, error.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function analyzeAudio(file) {
    if (!state.datasetId || !file) return;
    if (file.size > 25 * 1024 * 1024) {
      showMessage(analysisMessage, "Audio file exceeds the 25 MB limit.", "error");
      return;
    }
    const formData = new FormData();
    formData.append("file", file, file.name || "recording.webm");
    clearMessage(analysisMessage);
    resultsPanel.classList.add("hidden");
    setBusy(true, "Transcribing audio and analyzing your question...");

    try {
      const response = await fetch(
        `/datasets/${encodeURIComponent(state.datasetId)}/analyze/audio`,
        { method: "POST", body: formData },
      );
      if (!response.ok) throw new Error(await readError(response));
      const result = await response.json();
      questionInput.value = result.transcript;
      updateControls();
      renderResult(result, "voice");
      clearMessage(analysisMessage);
    } catch (error) {
      showMessage(analysisMessage, error.message, "error");
    } finally {
      setBusy(false);
    }
  }

  function stopRecording() {
    if (state.recorder && state.recorder.state !== "inactive") state.recorder.stop();
    if (state.stream) {
      state.stream.getTracks().forEach((track) => track.stop());
      state.stream = null;
    }
    recordButton.classList.remove("recording");
    recordButton.setAttribute("aria-label", "Start voice recording");
    byId("record-title").textContent = "Ask with your voice";
    byId("record-hint").textContent = "Record a question and we’ll analyze your dataset.";
  }

  async function toggleRecording() {
    if (state.recorder?.state === "recording") {
      stopRecording();
      return;
    }

    try {
      state.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      state.chunks = [];
      state.recorder = new MediaRecorder(state.stream);
      state.recorder.addEventListener("dataavailable", (event) => {
        if (event.data.size) state.chunks.push(event.data);
      });
      state.recorder.addEventListener("stop", () => {
        const blob = new Blob(state.chunks, { type: state.recorder.mimeType || "audio/webm" });
        const extension = blob.type.includes("ogg") ? "ogg" : "webm";
        stopRecording();
        if (blob.size) void analyzeAudio(new File([blob], `recording.${extension}`, { type: blob.type }));
      }, { once: true });
      state.recorder.start();
      recordButton.classList.add("recording");
      recordButton.setAttribute("aria-label", "Stop voice recording");
      byId("record-title").textContent = "Listening… click to finish";
      byId("record-hint").textContent = "Speak clearly, then press the microphone again.";
    } catch (error) {
      showMessage(analysisMessage, `Could not start microphone: ${error.message}`, "error");
    }
  }

  function downloadCsv() {
    if (!state.result) return;
    const { columns, rows } = state.result.results;
    const escapeCsv = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
    const csv = [
      columns.map(escapeCsv).join(","),
      ...rows.map((row) => columns.map((column) => escapeCsv(row[column])).join(",")),
    ].join("\r\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    link.download = "analysis-results.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  }

  fileInput.addEventListener("change", () => {
    if (fileInput.files?.[0]) void uploadDataset(fileInput.files[0]);
    fileInput.value = "";
  });
  for (const eventName of ["dragenter", "dragover"]) {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.add("dragover");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.remove("dragover");
    });
  }
  dropzone.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (file) void uploadDataset(file);
  });
  questionInput.addEventListener("input", updateControls);
  codeQuery.addEventListener("input", () => {
    codeSubmit.disabled = state.codeBusy || !codeQuery.value.trim();
  });
  byId("question-form").addEventListener("submit", (event) => {
    event.preventDefault();
    void analyzeText(questionInput.value);
  });
  byId("code-form").addEventListener("submit", (event) => {
    event.preventDefault();
    void askCodeAssistant(codeQuery.value);
  });
  byId("clear-code-chat").addEventListener("click", () => {
    byId("code-chat").replaceChildren();
    appendChatMessage(
      "assistant",
      "Hi! I can generate code, help debug an error, or explain a programming concept. What would you like to work on?",
    );
    clearMessage(byId("code-message"));
  });
  document.querySelectorAll("[data-app-tab]").forEach((button) => {
    button.addEventListener("click", () => selectApp(button.dataset.appTab));
  });
  document.querySelectorAll("[data-choose-app]").forEach((button) => {
    button.addEventListener("click", () => openWorkspace(button.dataset.chooseApp));
  });
  document.querySelectorAll("[data-code-mode]").forEach((button) => {
    button.addEventListener("click", () => selectCodeMode(button.dataset.codeMode));
  });
  byId("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = byId("login-submit");
    submit.disabled = true;
    clearMessage(byId("login-message"));
    try {
      const isRegistering = state.authMode === "register";
      const username = byId("login-username").value.trim();
      const password = byId("login-password").value;
      if (isRegistering && password !== byId("confirm-password").value) {
        throw new Error("Passwords do not match.");
      }
      const response = await fetch(isRegistering ? "/auth/register" : "/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username,
          password,
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      if (isRegistering) {
        setAuthMode("login");
        byId("login-username").value = username;
        byId("login-password").value = "";
        byId("confirm-password").value = "";
        showMessage(byId("login-message"), "Account created. Sign in with your new credentials.", "success");
        return;
      }
      byId("login-password").value = "";
      showChooser();
    } catch (error) {
      showMessage(byId("login-message"), error.message, "error");
    } finally {
      submit.disabled = false;
    }
  });
  document.querySelectorAll("[data-auth-mode]").forEach((button) => {
    button.addEventListener("click", () => setAuthMode(button.dataset.authMode));
  });
  document.querySelectorAll("[data-logout]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const response = await fetch("/auth/logout", { method: "POST" });
        if (!response.ok) throw new Error(await readError(response));
        showLogin();
      } catch (error) {
        showMessage(byId("login-message"), error.message, "error");
      }
    });
  });
  recordButton.addEventListener("click", () => void toggleRecording());
  byId("audio-file").addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (file) void analyzeAudio(file);
    event.target.value = "";
  });
  byId("download-results").addEventListener("click", downloadCsv);

  selectCodeMode(state.codeMode);
  selectApp("data");
  updateControls();
  void initializeAuth();
})();
