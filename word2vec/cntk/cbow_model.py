from __future__ import print_function
import numpy as np
import cntk as C
from cntk import Trainer
from cntk.learner import adam_sgd, UnitType, sgd, learning_rate_schedule, momentum_as_time_constant_schedule
from cntk.utils import ProgressPrinter
from cntk.layers import Embedding, GlobalAveragePooling
from cntk.models import Sequential
from cntk.initializer import uniform

import global_settings as G
from sentences_generator import Sentences
import vocab_generator as V_gen
import save_embeddings as S

k = G.window_size # context windows size
context_size = 2*k

# Creating a sentence generator from demo file
sentences = Sentences("test_file.txt")
vocabulary = dict()
V_gen.build_vocabulary(vocabulary, sentences)
V_gen.filter_vocabulary_based_on(vocabulary, G.min_count)
reverse_vocabulary = V_gen.generate_inverse_vocabulary_lookup(vocabulary, "vocab.txt")

# def cntk_pretraining_batch_generator(sentences, vocabulary, reverse_vocabulary):
# 	inputs, labels = pretraining_batch_generator(sentences, vocabulary, reverse_vocabulary)
# 	yield inputs

def cntk_minibatch_generator(minibatch_size, sentences, vocabulary, reverse_vocabulary):
	word_indexes = list()
	context_indexes = list()
	negative_indexes = list()
	i = 0
	for inputs in V_gen.pretraining_batch_generator(sentences, vocabulary, reverse_vocabulary):
		print(inputs)
		word_indexes.append(inputs[0])
		context_indexes.append(inputs[1])
		negative_indexes.append(inputs[2])
		i += 1
		if i == minibatch_size:
			break
	word_one_hot = C.one_hot(word_indexes, G.vocab_size)
	context_one_hots = C.one_hot(context_indexes, G.vocab_size)
	negative_one_hots = C.one_hot(negative_indexes, G.vocab_size)

	print("word one hot input shape = ", word_one_hot.shape)
	print("context one hot input shape = ", context_one_hots.shape)
	print("negative one hot input shape = ", negative_one_hots.shape)
	yield word_one_hot, context_one_hots, negative_one_hots

def create_word2vec_cbow_model(word_one_hot, context_one_hots, negative_one_hots):
	# shared_embedding_layer = Embedding(G.embedding_dimension, uniform(scale=1.0/2.0/G.embedding_dimension))
	shared_embedding_layer = Embedding(G.embedding_dimension)

	word_embedding = shared_embedding_layer(word_one_hot)
	context_embeddings = shared_embedding_layer(context_one_hots)
	negative_embeddings = shared_embedding_layer(negative_one_hots)

	print(word_embedding.shape)
	word_embedding_reshaped = C.reshape(word_embedding, shape=(1, G.embedding_dimension))
	print(word_embedding_reshaped.shape)
	print(context_embeddings.shape)
	print(negative_embeddings.shape)

	cbow = C.reshape(C.reduce_mean(context_embeddings, 0), shape=(G.embedding_dimension))
	print(cbow.shape)

	# word_context_product = C.times_transpose(word_embedding_reshaped, cbow)
	word_context_product = C.times_transpose(word_embedding, cbow)
	print(word_context_product.shape)
	negative_context_product = C.reshape(C.times_transpose(negative_embeddings, cbow), shape=(G.negative))
	print(negative_context_product.shape)

	word_negative_context_product = C.splice((word_context_product, negative_context_product))
	print(word_negative_context_product.shape)
	# return model and shared embedding layer
	return word_negative_context_product, shared_embedding_layer

def create_trainer():
	# Will take the model and the batch generator to create a Trainer
	# Will return the input variables, trainer variable, model and the embedding layer
	##################################################
	################### Inputs #######################
	##################################################
	word_one_hot = C.input_variable((G.vocab_size), np.float32)
	context_one_hots = C.input_variable((context_size, G.vocab_size), np.float32)
	negative_one_hots = C.input_variable((G.negative, G.vocab_size), np.float32)

	# Creating the target labels where first is 1 and others are 0
	target = np.zeros((G.negative + 1))
	target.itemset(0, 1)

	word_negative_context_product, embedding_layer = create_word2vec_cbow_model(word_one_hot, context_one_hots, negative_one_hots)
	loss = C.binary_cross_entropy(word_negative_context_product, target)
	eval_loss = C.binary_cross_entropy(word_negative_context_product, target)

	lr_schedule = learning_rate_schedule(G.learning_rate, UnitType.minibatch)

	learner = adam_sgd(word_negative_context_product.parameters, lr = lr_schedule, momentum = momentum_as_time_constant_schedule(700))

	trainer = Trainer(word_negative_context_product, loss, eval_loss, learner)

	return word_one_hot, context_one_hots, negative_one_hots, trainer, word_negative_context_product, embedding_layer

def train():
	global sentences, vocabulary, reverse_vocabulary
	
	# function will create the trainer and train it for specified number of epochs

	G.num_minibatches = G.train_words // G.minibatch_size
	
	# Print loss 50 times while training
	print_freqency = G.num_minibatches // 50
	pp = ProgressPrinter(print_freqency)

	# get the trainer
	word_one_hot, context_one_hots, negative_one_hots, trainer, word_negative_context_product, embedding_layer = create_trainer()
	# Get the input generator
	minibatch_generator = cntk_minibatch_generator(G.minibatch_size, sentences, vocabulary, reverse_vocabulary)
	for train_steps in range(G.num_minibatches):
		# Get mini_batch and train for one minibatch
		word, context, negatives = next(minibatch_generator)
		trainer.train_minibatch({word_one_hot: word, context_one_hots: context, negative_one_hots: negatives})
		pp.update_with_trainer(trainer)

train()
