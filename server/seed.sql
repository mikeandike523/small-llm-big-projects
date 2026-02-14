INSERT INTO known_providers (provider_key, display_name, default_endpoint_url)
VALUES
  ('openai',  'OpenAI (GPT)',            'https://api.openai.com/v1'),
  ('gpt',  'OpenAI (GPT)',            'https://api.openai.com/v1'),
  ('anthropic',  'Anthropic Claude',  'https://api.anthropic.com/v1'),
  ('claude',  'Anthropic Claude',  'https://api.anthropic.com/v1'),
  ('local',   'Local',             'http://localhost:11434')
AS new
ON DUPLICATE KEY UPDATE
  display_name = new.display_name,
  default_endpoint_url = new.default_endpoint_url;
