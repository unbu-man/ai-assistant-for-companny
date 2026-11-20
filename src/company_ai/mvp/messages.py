"""Customer wording for the supported reply languages."""

MESSAGES = {
    "welcome": ("Hi! What can I help you with?", "សួស្តី! តើខ្ញុំអាចជួយអ្នកអ្វីបានខ្លះ?"),
    "scope": (
        "A quotation depends on your requirements. What type of business do you run, and which modules or workflows do you need?",
        "ការដាក់សម្រង់តម្លៃអាស្រ័យលើតម្រូវការរបស់អ្នក។ តើអ្នកមានអាជីវកម្មប្រភេទអ្វី ហើយត្រូវការម៉ូឌុល ឬដំណើរការការងារអ្វីខ្លះ?",
    ),
    "consent": (
        "May we share your name and phone number or Telegram with the sales team for your quotation?",
        "តើយើងអាចចែករំលែកឈ្មោះ និងលេខទូរស័ព្ទ ឬ Telegram របស់អ្នកជាមួយក្រុមលក់ ដើម្បីរៀបចំសម្រង់តម្លៃបានទេ?",
    ),
    "contact": (
        "Please enter your name and either a phone number or Telegram username.",
        "សូមបញ្ចូលឈ្មោះ និងលេខទូរស័ព្ទ ឬឈ្មោះអ្នកប្រើ Telegram របស់អ្នក។",
    ),
    "cancelled": (
        "Your quotation request was cancelled. How else can I help?",
        "សំណើសុំសម្រង់តម្លៃត្រូវបានបោះបង់។ តើខ្ញុំអាចជួយអ្វីផ្សេងទៀតបានទេ?",
    ),
    "saved": (
        "Your quotation request has been saved. Your reference is {reference}.",
        "សំណើសុំសម្រង់តម្លៃរបស់អ្នកត្រូវបានរក្សាទុក។ លេខយោងរបស់អ្នកគឺ {reference}។",
    ),
    "unknown": (
        "I don’t have a verified answer for that yet. Could you tell me a little more about what you need?",
        "ខ្ញុំមិនទាន់មានចម្លើយដែលបានផ្ទៀងផ្ទាត់ទេ។ តើអ្នកអាចប្រាប់បន្ថែមអំពីអ្វីដែលអ្នកត្រូវការបានទេ?",
    ),
    "procedure_unknown": (
        "I don’t have verified steps for that yet. Which product and version are you using?",
        "ខ្ញុំមិនទាន់មានជំហានដែលបានផ្ទៀងផ្ទាត់ទេ។ តើអ្នកកំពុងប្រើផលិតផល និងកំណែអ្វី?",
    ),
    "procedure_unavailable": (
        "I don’t have verified steps for that version. What are you trying to accomplish? I can check for a feature overview.",
        "ខ្ញុំមិនទាន់មានជំហានដែលបានផ្ទៀងផ្ទាត់សម្រាប់កំណែនោះទេ។ តើអ្នកចង់ធ្វើអ្វី? ខ្ញុំអាចពិនិត្យព័ត៌មានទូទៅអំពីមុខងារនោះបាន។",
    ),
    "tenant": (
        "This conversation is for {company}. Please start a new chat with the other company to ask about its services.",
        "ការសន្ទនានេះសម្រាប់ {company}។ សូមចាប់ផ្តើមការសន្ទនាថ្មីជាមួយក្រុមហ៊ុននោះ ដើម្បីសួរអំពីសេវាកម្មរបស់ពួកគេ។",
    ),
}


def say(key: str, language: str, **kwargs: str) -> str:
    return MESSAGES[key][language == "km"].format(**kwargs)
