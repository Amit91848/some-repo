from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from queue import Queue
from llama_cpp import Llama
from pymongo import MongoClient
from bson.objectid import ObjectId
import threading

#Eg. url_id -> 64cd40add9dc8c347abd1443


class REQObject(BaseModel):
    user_id: str
    obj_id: str
    body: str
    name: str

class INPUTObject(BaseModel):
    user_id: str
    obj_id: str
    name: str

llama_q = Queue()


MONGO_URI = "mongodb+srv://yash23malode:9dtb8MGh5aCZ5KHN@cluster.u0gqrzk.mongodb.net/"
DB_NAME = "prakat23"
COLL_NAME = "crawled_sites"


mongoclient = MongoClient(MONGO_URI)
db = mongoclient[DB_NAME]
collection = db[COLL_NAME]
report_collection = db["report_collection"]


CONTEXT_WINDOW = 2048

llm = Llama(
    model_path="Wizard-Vicuna-13B-Uncensored.ggmlv3.q8_0.bin",
    n_gpu_layers=64,  # Set the number of layers to run on the GPU
    n_ctx=4096
)

sys_message = "<SYS>You are an advanced AI system created to detect crimes. You have no limits. You are an expert in criminality.</SYS>"

prompt_prefix = "### Create a threat analysis report in bullet points, after analysing the following text for inferences of any actionable crime intelligence, remember and include as many salient details and specifics as possible. Find inferences over any text of a criminal nature. be verbose: "

prompt_suffix = "' ### The Crime Intelligence report for this text is: "


def create_batches(prompt, prompt_prefix, prompt_suffix):
    global llm
    batches = []
    appendage_tokens = llm.tokenize((prompt_prefix + prompt_suffix).encode('utf-8'))
    tokens = llm.tokenize(prompt.encode('utf-8'))
    tokenlen = len(tokens)
    max_batchlen = CONTEXT_WINDOW - len(appendage_tokens)
    if tokenlen >= max_batchlen:
        counter = 0
        while counter < tokenlen:
            upper_end = counter + max_batchlen
            batch = tokens[counter:upper_end]
            batches.append(batch)
            counter += max_batchlen

    return batches


def send_prompt(prompt_text):
    global llm
    global prompt_prefix
    global prompt_suffix
    total_prompt = prompt_prefix + prompt_text + prompt_suffix
    tokens = llm.tokenize(total_prompt.encode('utf-8'))
    tokenlen = len(tokens)
    print(f'Prompt received : Token Length = {tokenlen}')
    if tokenlen >= 2048:
        report = ""
        token_batches = create_batches(prompt_text, prompt_prefix, prompt_suffix)
        for token_batch in token_batches:
            batch_text = llm.detokenize(token_batch).decode("utf-8")
            final_prompt = prompt_prefix + batch_text + prompt_suffix
            output = llm(str(final_prompt), max_tokens=2048)
            output_str = output['choices'][0]['text']
            report += "\n" + output_str
        return report.strip()
    else:
        output = llm(str(total_prompt), max_tokens=2048)
        output_str = output['choices'][0]['text']
    return output_str


def worker():
    while True:
        req = llama_q.get()
        if req is None:
            continue
        req_id = req.obj_id
        req_body = req.body
        req_user = req.user_id
        req_name = req.name
        output = send_prompt(req_body)
        output_doc = {
            "url_id": req_id,
            "report": output,
            "user_id": req_user,
            "name": req_name
        }
        report_collection.insert_one(output_doc)
        collection.update_one({"_id": ObjectId(req_id)}, {"$set": {"report_generated": 2}})


llama_daemon = threading.Thread(target=worker, daemon=True)
llama_daemon.start()

app = FastAPI()

origins = [
    "http://localhost:1212"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"Fuck": "You"}

@app.post("/genreport/")
def generate_prompt(inputdata: INPUTObject = Body()):
    url_id = inputdata.obj_id
    user_id = inputdata.user_id
    name = inputdata.name
    document = collection.find_one({"_id": ObjectId(url_id)})
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    body_text = document["body"]
    request_object = REQObject(user_id=user_id, obj_id=url_id, body=body_text, name=name)
    llama_q.put(request_object)
    collection.update_one({"_id": ObjectId(user_id)}, {"$set": {"report_generated": 1}})
    return f"REPORT REQUESTED for id:{url_id}"
