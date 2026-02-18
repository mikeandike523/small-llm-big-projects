from typing import Optional
import requests

class StreamingLLM:

    _endpoint: str
    _token: str
    _model: Optional[str]
    _default_parameters: dict

    def __init__(self, endpoint, token, model=None, default_parameters={}):
        self._endpoint = endpoint
        self._token = token
        self._model = model
        self._default_parameters = {}

    def stream(
        self,
        messages,
        max_tokens=None,
        parameters={} 
    ):
        payload = {}
        payload.update(self._default_parameters)
        if self._model:
            payload["model"] = self._model
        if parameters:
            payload.update(parameters)
        payload["messages"]=messages
        payload["max_tokens"]=max_tokens

        headers={
            "Authorization":f"Bearer {self._token}"
        }




