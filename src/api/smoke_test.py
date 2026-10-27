from foundry_client import chat_client, embed_client, CHAT_DEPLOYMENT, EMBED_DEPLOYMENT

chat = chat_client().chat.completions.create(
    model=CHAT_DEPLOYMENT,
    messages=[{"role": "user", "content": "Say hello in one sentence."}],
)
print("CHAT:", chat.choices[0].message.content)

emb = embed_client().embeddings.create(model=EMBED_DEPLOYMENT, input="windscreen cover for Plus customers")
print("EMBEDDING LENGTH:", len(emb.data[0].embedding))
