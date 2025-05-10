// Fixed provider configuration functions

// Get fallbacks configuration from UI
function getFallbacksConfig(componentPrefix) {
  const fallbackListId = `${componentPrefix}-fallback-list`;
  const fallbackList = document.getElementById(fallbackListId);

  console.log(
    `[GetFallbacks] Processing component: ${componentPrefix}. List ID: ${fallbackListId}`
  );

  if (!fallbackList) {
    console.warn(
      `[GetFallbacks] Fallback list with ID '${fallbackListId}' NOT FOUND for ${componentPrefix}.`
    );
    return [];
  }

  const fallbacks = [];
  const fallbackItems = fallbackList.querySelectorAll(".fallback-item");

  console.log(
    `[GetFallbacks] Found ${fallbackItems.length} fallback items for ${componentPrefix}.`
  );

  Array.from(fallbackItems).forEach((item, index) => {
    // Try both class naming conventions to handle potential inconsistencies in the HTML/JS
    const providerSelect =
      item.querySelector(".provider-select") ||
      item.querySelector(".fallback-provider-select");

    const modelSelect =
      item.querySelector(".model-select") ||
      item.querySelector(".fallback-model-select");

    // Log the raw values obtained from the DOM elements
    const rawProviderId = providerSelect
      ? providerSelect.value
      : "PROVIDER_SELECT_NOT_FOUND";
    const rawModelId = modelSelect
      ? modelSelect.value
      : "MODEL_SELECT_NOT_FOUND";

    console.log(
      `[GetFallbacks] Item ${index} for ${componentPrefix}: Provider='${rawProviderId}', Model='${rawModelId}'`
    );

    if (!providerSelect) {
      console.warn(
        `[GetFallbacks] Item ${index} for ${componentPrefix}: Provider select element NOT FOUND.`
      );
    }

    if (!modelSelect) {
      console.warn(
        `[GetFallbacks] Item ${index} for ${componentPrefix}: Model select element NOT FOUND.`
      );
    }

    if (providerSelect && providerSelect.value) {
      fallbacks.push({
        provider: providerSelect.value,
        model: modelSelect ? modelSelect.value : "",
      });
      console.log(
        `[GetFallbacks] Added fallback for ${componentPrefix}: Provider='${
          providerSelect.value
        }', Model='${modelSelect ? modelSelect.value : ""}'`
      );
    }
  });

  console.log(
    `[GetFallbacks] Returning ${fallbacks.length} fallbacks for ${componentPrefix}:`,
    JSON.stringify(fallbacks)
  );
  return fallbacks;
}

// Add a new fallback provider
function addFallbackProvider(aiComponent) {
  console.log(`Adding new fallback provider for component ${aiComponent}`);

  // Get the main provider for this component to use as initial fallback
  const mainProviderSelect =
    document.getElementById(`${aiComponent}-provider-select`) ||
    document.getElementById(`${aiComponent}-provider`);
  if (!mainProviderSelect) {
    console.error(`Could not find main provider select for ${aiComponent}`);
    return;
  }

  // Find the fallback list container
  const fallbackList = document.getElementById(`${aiComponent}-fallback-list`);
  if (!fallbackList) {
    console.error(`Could not find fallback list for ${aiComponent}`);
    return;
  }

  const mainProvider = mainProviderSelect.value;
  const position = fallbackList.children.length;

  console.log(
    `Adding fallback provider at position ${position} for ${aiComponent} with initial provider ${mainProvider}`
  );

  // Add to UI
  addFallbackToUI(aiComponent, mainProvider, "", position);
}

// Add a fallback provider to the UI
function addFallbackToUI(aiComponent, provider, model, position) {
  console.log(
    `Adding fallback to UI for component ${aiComponent} with provider ${provider}, model ${model}, at position ${position}`
  );

  const fallbackList = document.getElementById(`${aiComponent}-fallback-list`);
  if (!fallbackList) {
    console.error(`Fallback list not found for component ${aiComponent}`);
    return;
  }

  const fallbackId = `${aiComponent}-fallback-${position}`;
  console.log(`Creating fallback with ID ${fallbackId}`);

  // Create fallback item
  const fallbackItem = document.createElement("div");
  fallbackItem.className = "fallback-item";
  fallbackItem.id = fallbackId;
  fallbackItem.dataset.position = position;

  // Create provider select - use both class names for consistency
  const providerSelect = document.createElement("select");
  providerSelect.className = "provider-select fallback-provider-select";
  providerSelect.id = `${fallbackId}-provider`;

  // Add a loading placeholder
  const loadingOption = document.createElement("option");
  loadingOption.value = "";
  loadingOption.textContent = "Loading providers...";
  providerSelect.appendChild(loadingOption);

  // If provider is specified, add it temporarily
  if (provider) {
    const providerOption = document.createElement("option");
    providerOption.value = provider;
    providerOption.textContent = provider;
    providerOption.selected = true;
    providerSelect.appendChild(providerOption);
  }

  // Fetch all providers and populate the select
  fetch("/providers")
    .then((response) => {
      if (!response.ok) {
        throw new Error(`Failed to fetch providers: ${response.statusText}`);
      }
      return response.json();
    })
    .then((data) => {
      if (data.available_providers && Array.isArray(data.available_providers)) {
        // Clear the select
        providerSelect.innerHTML = "";

        // Add providers
        data.available_providers.forEach((p) => {
          const option = document.createElement("option");
          option.value = p;
          option.textContent = p;
          option.selected = p === provider;
          providerSelect.appendChild(option);
        });

        console.log(
          `Loaded ${data.available_providers.length} providers for fallback ${fallbackId}`
        );
      } else {
        console.error("Invalid provider data received:", data);
        providerSelect.innerHTML =
          "<option value=''>No providers available</option>";
      }
    })
    .catch((error) => {
      console.error("Error fetching providers:", error);
      providerSelect.innerHTML =
        "<option value=''>Error loading providers</option>";
    });

  // Create model select - use both class names for consistency
  const modelSelect = document.createElement("select");
  modelSelect.className = "model-select fallback-model-select";
  modelSelect.id = `${fallbackId}-model`;

  // Add a placeholder option
  const placeholderOption = document.createElement("option");
  placeholderOption.value = "";
  placeholderOption.textContent = "Default model";
  modelSelect.appendChild(placeholderOption);

  // If model is provided, add it as an option
  if (model) {
    const modelOption = document.createElement("option");
    modelOption.value = model;
    modelOption.textContent = model;
    modelOption.selected = true;
    modelSelect.appendChild(modelOption);
  }

  // Set up provider change event to update models
  providerSelect.addEventListener("change", () => {
    updateFallbackModelOptions(fallbackId);
  });

  // Create control buttons container
  const fallbackControls = document.createElement("div");
  fallbackControls.className = "fallback-controls";

  // Create remove button
  const removeButton = document.createElement("button");
  removeButton.className = "fallback-remove-btn";
  removeButton.title = "Remove fallback";
  removeButton.innerHTML = '<i class="fas fa-times"></i>';
  removeButton.addEventListener("click", () =>
    removeFallback(aiComponent, fallbackId)
  );

  // Create move up button
  const moveUpButton = document.createElement("button");
  moveUpButton.className = "fallback-move-btn";
  moveUpButton.title = "Move up";
  moveUpButton.innerHTML = '<i class="fas fa-arrow-up"></i>';
  moveUpButton.addEventListener("click", () =>
    moveFallback(aiComponent, fallbackId, "up")
  );

  // Create move down button
  const moveDownButton = document.createElement("button");
  moveDownButton.className = "fallback-move-btn";
  moveDownButton.title = "Move down";
  moveDownButton.innerHTML = '<i class="fas fa-arrow-down"></i>';
  moveDownButton.addEventListener("click", () =>
    moveFallback(aiComponent, fallbackId, "down")
  );

  // Add buttons to controls
  fallbackControls.appendChild(moveUpButton);
  fallbackControls.appendChild(moveDownButton);
  fallbackControls.appendChild(removeButton);

  // Add elements to the fallback item
  fallbackItem.appendChild(providerSelect);
  fallbackItem.appendChild(modelSelect);
  fallbackItem.appendChild(fallbackControls);

  // Add fallback item to the list
  fallbackList.appendChild(fallbackItem);

  // Update model options
  updateFallbackModelOptions(fallbackId);

  console.log(`Fallback ${fallbackId} added to the UI`);
}

// Save provider configuration
async function saveProviderConfig() {
  console.log("Saving provider configuration...");

  // Show loading indicator
  showNotification("Saving provider configuration...", "info");

  // Create configuration object
  const config = {
    ai1: {
      provider: document.getElementById("ai1-provider").value,
      model: document.getElementById("ai1-model").value,
      fallbacks: getFallbacksConfig("ai1"),
    },
    ai2: {
      executor: {
        provider: document.getElementById("ai2-executor-provider").value,
        model: document.getElementById("ai2-executor-model").value,
        fallbacks: getFallbacksConfig("ai2-executor"),
      },
      tester: {
        provider: document.getElementById("ai2-tester-provider").value,
        model: document.getElementById("ai2-tester-model").value,
        fallbacks: getFallbacksConfig("ai2-tester"),
      },
      documenter: {
        provider: document.getElementById("ai2-documenter-provider").value,
        model: document.getElementById("ai2-documenter-model").value,
        fallbacks: getFallbacksConfig("ai2-documenter"),
      },
    },
    ai3: {
      provider: document.getElementById("ai3-provider").value,
      model: document.getElementById("ai3-model").value,
      fallbacks: getFallbacksConfig("ai3"),
      structure_provider: document.getElementById("ai3-structure-provider")
        .value,
      structure_model: document.getElementById("ai3-structure-model").value,
      structure_fallbacks: getFallbacksConfig("ai3-structure"), // Make sure this is included
    },
  };

  console.log("Provider config to save:", JSON.stringify(config, null, 2));

  try {
    // Send configuration to server
    const response = await fetch("/update_providers", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(config),
    });

    const result = await response.json();

    if (result.status === "success") {
      showNotification("Provider configuration saved successfully", "success");
    } else {
      showNotification(`Error: ${result.message || "Unknown error"}`, "error");
    }
  } catch (error) {
    console.error("Error saving provider configuration:", error);
    showNotification("Error saving provider configuration", "error");
  }
}
