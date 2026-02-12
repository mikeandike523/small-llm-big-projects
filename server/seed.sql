INSERT INTO known_providers (provider_key, display_name, default_endpoint_url)
VALUES
  ('openai',  'OpenAI',            'https://api.openai.com/v1'),
  ('claude',  'Anthropic Claude',  'https://api.anthropic.com/v1'),
  ('local',   'Local',             'http://localhost:11434')
ON DUPLICATE KEY UPDATE
  display_name = VALUES(display_name),
  default_endpoint_url = VALUES(default_endpoint_url);