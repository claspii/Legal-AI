import os
import argparse
from unsloth import FastLanguageModel
import torch

def main():
    parser = argparse.ArgumentParser(description="Merge Unsloth LoRA checkpoint and export to GGUF Q8_0")
    parser.add_argument(
        "--checkpoint", 
        type=str, 
        required=True, 
        help="Path to the LoRA adapter checkpoint (e.g., ./legal_qwen35_output/checkpoint-100 or legal_qwen35_lora)"
    )
    parser.add_argument(
        "--output_dir", 
        type=str, 
        default="legal_qwen35_q8_0", 
        help="Directory name to save the GGUF model"
    )
    parser.add_argument(
        "--max_seq_length", 
        type=int, 
        default=8192, 
        help="Max sequence length used during training"
    )
    args = parser.parse_args()

    print(f"Loading base model and applying LoRA adapter from: {args.checkpoint}...")
    
    # Load model and tokenizer
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name = args.checkpoint,
        max_seq_length = args.max_seq_length,
        load_in_4bit = True,
    )
    
    print("Model loaded successfully!")
    print(f"Merging and exporting to GGUF Q8_0 format in directory: {args.output_dir}...")
    
    # Save to GGUF format locally
    model.save_pretrained_gguf(
        args.output_dir,
        tokenizer,
        quantization_method = "q8_0",
    )
    
    print("=" * 60)
    print(f"✅ Merging and export complete! GGUF files saved in: {args.output_dir}/")
    print("=" * 60)

if __name__ == "__main__":
    main()
