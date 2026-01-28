from app.models.schemas import ActionItem, AnalysisResult
from app.services.document_service import generate_document
from app.utils import file_utils

analysis = AnalysisResult(
    summary="This is a test summary.",
    participants=["Alice", "Bob"],
    decisions=["Proceed with the launch"],
    action_items=[
        ActionItem(description="Prepare slides", owner="Alice"),
        ActionItem(description="Send email", owner=None),
    ],
    translated_transcript="This is a short meeting transcript.",
)

path = generate_document(analysis)
print(f"Document created at: {path}")
file_utils.delete_temp_file(path)
