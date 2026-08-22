from pydantic import BaseModel


class ArtifactRef(BaseModel):
    uri: str
