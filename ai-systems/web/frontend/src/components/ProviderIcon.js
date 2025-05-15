import React from 'react';
import { Box, Tooltip } from '@mui/material';
import SmartToyIcon from '@mui/icons-material/SmartToy';

/**
 * ProviderIcon component displays an icon for a specific AI provider
 * @param {Object} props - Component props
 * @param {String} props.provider - Provider ID
 * @param {String} props.size - Icon size (small, medium, large)
 * @param {Boolean} props.showTooltip - Whether to show a tooltip with the provider name
 */
const ProviderIcon = ({ provider, size = 'medium', showTooltip = true }) => {
  // Define size values
  const sizeMap = {
    small: 16,
    medium: 24,
    large: 32
  };
  
  const iconSize = sizeMap[size] || sizeMap.medium;
  
  // Map of provider IDs to their respective logos/icons
  const providerIcons = {
    openai: '/icons/openai.svg',
    anthropic: '/icons/anthropic.svg',
    gemini: '/icons/gemini.svg',
    mistral: '/icons/mistral.svg',
    codestral: '/icons/codestral.svg',
    cohere: '/icons/cohere.svg',
    groq: '/icons/groq.svg',
    together: '/icons/together.svg',
    openrouter: '/icons/openrouter.svg',
    ollama: '/icons/ollama.svg',
    ollama_local: '/icons/ollama.svg',
    ollama_remote: '/icons/ollama.svg',
    huggingface: '/icons/huggingface.svg',
    grok: '/icons/grok.svg',
    replicate: '/icons/replicate.svg',
    perplexity: '/icons/perplexity.svg',
    anyscale: '/icons/anyscale.svg',
    deepinfra: '/icons/deepinfra.svg',
    fireworks: '/icons/fireworks.svg',
    local: '/icons/local.svg'
  };
  
  // Provider display names for tooltips
  const providerNames = {
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    gemini: 'Google Gemini',
    mistral: 'Mistral AI',
    codestral: 'Codestral',
    cohere: 'Cohere',
    groq: 'Groq',
    together: 'Together AI',
    openrouter: 'OpenRouter',
    ollama: 'Ollama',
    ollama_local: 'Ollama (Local)',
    ollama_remote: 'Ollama (Remote)',
    huggingface: 'Hugging Face',
    grok: 'Grok',
    replicate: 'Replicate',
    perplexity: 'Perplexity',
    anyscale: 'Anyscale',
    deepinfra: 'DeepInfra',
    fireworks: 'Fireworks',
    local: 'Local Models'
  };
  
  // Get the icon path for the provider
  const iconPath = providerIcons[provider];
  
  // If no icon is available, use a default icon
  if (!iconPath) {
    return (
      <Tooltip title={showTooltip ? (providerNames[provider] || provider) : ''}>
        <SmartToyIcon sx={{ width: iconSize, height: iconSize }} />
      </Tooltip>
    );
  }
  
  // Create the icon component
  const icon = (
    <Box
      component="img"
      src={iconPath}
      alt={`${provider} icon`}
      sx={{
        width: iconSize,
        height: iconSize,
        objectFit: 'contain'
      }}
    />
  );
  
  // Wrap in tooltip if needed
  if (showTooltip) {
    return (
      <Tooltip title={providerNames[provider] || provider}>
        {icon}
      </Tooltip>
    );
  }
  
  return icon;
};

export default ProviderIcon;
