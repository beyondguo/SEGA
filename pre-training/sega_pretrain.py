import numpy as np
import nltk
nltk.download('stopwords')
nltk.download('punkt')
from nltk.tokenize import sent_tokenize
import transformers
from transformers import AutoTokenizer, AutoModel, AutoConfig, AutoModelForSeq2SeqLM
from transformers import Seq2SeqTrainingArguments, Seq2SeqTrainer, DataCollatorForSeq2Seq
from datasets import load_dataset, load_metric
import argparse
parser = argparse.ArgumentParser(allow_abbrev=False)
parser.add_argument('--sketch_type', type=str, default=None, help='1,2,3 or 4. Details see pre-training/prepare_sega_pretrain_data.py')
args = parser.parse_args()



# pretrained checkpoint:
model_checkpoint = 'facebook/bart-large'  
tokenizer = AutoTokenizer.from_pretrained(model_checkpoint)


##################################################################
#                     data pre-processing
##################################################################

# load the preprocessed dataset with the four kinds of sketches
from datasets import load_from_disk
dataset_path = '../saved_datasets/c4-realnewslike-4templates-passage-and-sent-max15sents_2' 
dataset_name = dataset_path.split('/')[-1]
dataset_with_sketch = load_from_disk(dataset_path)
print(dataset_with_sketch)

# define the inputs and labels for sketch-based reconstruction pre-training
max_input_length = 100
max_target_length = 300
print("********** Sketch type is: ", args.sketch_type)
def preprocess_function(examples):
    """
    # inputs: the sketch
    # labels: the original text
    """
    model_inputs = tokenizer(examples[f'sketch_{args.sketch_type}'], max_length=max_input_length, truncation=True)
    with tokenizer.as_target_tokenizer():
        labels = tokenizer(examples['text'], max_length=max_target_length, truncation=True)
    model_inputs['labels'] = labels['input_ids']
    return model_inputs

tokenized_dataset = dataset_with_sketch.map(preprocess_function, batched=True, 
                                         batch_size=10000,num_proc=100)


# ROUGE metric：
rouge_score = load_metric("rouge")
def compute_metrics(eval_pred):
    predictions, labels = eval_pred
    # Decode generated summaries into text
    decoded_preds = tokenizer.batch_decode(predictions, skip_special_tokens=True)
    # Replace -100 in the labels as we can't decode them
    labels = np.where(labels != -100, labels, tokenizer.pad_token_id)
    # Decode reference summaries into text
    decoded_labels = tokenizer.batch_decode(labels, skip_special_tokens=True)
    # ROUGE expects a newline after each sentence
    decoded_preds = ["\n".join(sent_tokenize(pred.strip())) for pred in decoded_preds]
    decoded_labels = ["\n".join(sent_tokenize(label.strip())) for label in decoded_labels]
    # Compute ROUGE scores
    result = rouge_score.compute(
        predictions=decoded_preds, references=decoded_labels, use_stemmer=True
    )
    # Extract the median scores
    result = {key: value.mid.fmeasure * 100 for key, value in result.items()}
    return {k: round(v, 4) for k, v in result.items()}


##################################################################
#                     training
##################################################################

batch_size = 40
num_train_epochs = 3
model_name = model_checkpoint.split("/")[-1]

# load the pretrained weights
model = AutoModelForSeq2SeqLM.from_pretrained(model_checkpoint)
# load only the model, without weights
# config = AutoConfig.from_pretrained(model_checkpoint)
# model =  AutoModel.from_config(config)


logging_steps = len(tokenized_dataset['train']) // batch_size

output_dir = f"../saved_models/{model_name}-{dataset_name}-sketch{args.sketch_type}"

training_args = Seq2SeqTrainingArguments(
    output_dir=output_dir,
    evaluation_strategy="steps",
    eval_steps = 10000,      
    save_strategy = 'epoch',
    save_total_limit = num_train_epochs,
    fp16 = True,
    learning_rate=5.6e-5,
    per_device_train_batch_size=batch_size,
    per_device_eval_batch_size=batch_size,
    weight_decay=0.01,
    num_train_epochs=num_train_epochs,
    predict_with_generate=True,
    logging_steps=logging_steps,
)

data_collator = DataCollatorForSeq2Seq(tokenizer, model=model)

# 如果没有验证集
# temp_evaluation_dataset = tokenized_dataset.select(range(2000))

# remove训练中不需要的column
tokenized_dataset["train"] = tokenized_dataset["train"].remove_columns(dataset_with_sketch["train"].column_names)
tokenized_dataset["validation"] = tokenized_dataset["validation"].remove_columns(dataset_with_sketch["validation"].column_names)

trainer = Seq2SeqTrainer(
    model,
    training_args,
    train_dataset=tokenized_dataset["train"],
    eval_dataset=tokenized_dataset["validation"], 
    data_collator=data_collator,
    tokenizer=tokenizer,
    compute_metrics=compute_metrics,
)


trainer.train(resume_from_checkpoint = False)
# save_path = output_dir+"-final"
# trainer.save_model(save_path)

# -----------------------------
import os
# os.system("cd ..")
# os.system("sh oc.sh")
os.system("python /mnt/data/occupy.py")