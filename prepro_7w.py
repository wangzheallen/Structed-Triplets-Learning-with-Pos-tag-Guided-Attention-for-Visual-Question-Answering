"""
Preoricess a raw json dataset into hdf5/json files.

Caption: Use NLTK or split function to get tokens.
"""
import copy
from random import shuffle, seed
import sys
import os.path
import argparse
import glob
import numpy as np
from scipy.misc import imread, imresize
import scipy.io
import pdb
import string
import h5py
from nltk.tokenize import word_tokenize
import json
import pdb
from autocorrect import spell
import re

def tokenize(sentence):
    return [i for i in re.split(r"([-.\"',:? !\$#@~()*&\^%;\[\]/\\\+<>\n=])", sentence) if i!='' and i!=' ' and i!='\n'];

def nltk_tokenize(sent):
    sent = str(sent).lower()
    sent = sent.replace("-", " ")
    sent = sent.replace("/", " ")
    sent = sent.replace("`", " ")
    token = word_tokenize(sent)

    for i in range(len(token)):
        if token[i].isalpha():
            token[i] = spell(token[i]).lower()
    return token


def prepro_question(imgs, params):

    # preprocess all the question and candidate answer
    print 'example processed tokens:'
    for i,img in enumerate(imgs):
        s = img['question']
        if params['token_method'] == 'nltk':
            txt = word_tokenize(str(s).lower())
        else:
            txt = tokenize(s)
        img['processed_tokens'] = txt

        # preprocess candidate answer
        ans = img['MC_ans']
        if params['token_method'] == 'nltk':
            ans_txt = word_tokenize(str(ans).lower())
        else:
            ans_txt = tokenize(ans)
        img['processed_ans'] = ans_txt

        if i < 10: print txt
        if i % 1000 == 0:
            sys.stdout.write("processing question %d/%d (%.2f%% done)   \r" %  (i, len(imgs), i*100.0/len(imgs)) )
            sys.stdout.flush()

    return imgs

def build_vocab_question(imgs, params):
    # build vocabulary for question and answers.

    count_thr = params['word_count_threshold']

    # count up the number of words
    counts = {}
    for img in imgs:
        for w in img['processed_tokens']:
            counts[w] = counts.get(w, 0) + 1
        for w in img['processed_ans']:
            counts[w] = counts.get(w, 0) + 1
    cw = sorted([(count,w) for w,count in counts.iteritems()], reverse=True)
    print 'top words and their counts:'
    print '\n'.join(map(str,cw[:20]))

    # print some stats
    total_words = sum(counts.itervalues())
    print 'total words:', total_words
    bad_words = [w for w,n in counts.iteritems() if n <= count_thr]
    vocab = [w for w,n in counts.iteritems() if n > count_thr]
    bad_count = sum(counts[w] for w in bad_words)
    print 'number of bad words: %d/%d = %.2f%%' % (len(bad_words), len(counts), len(bad_words)*100.0/len(counts))
    print 'number of words in vocab would be %d' % (len(vocab), )
    print 'number of UNKs: %d/%d = %.2f%%' % (bad_count, total_words, bad_count*100.0/total_words)


    # lets now produce the final annotation
    # additional special UNK token we will use below to map infrequent words to
    print 'inserting the special UNK token'
    vocab.append('UNK')

    for img in imgs:
        txt = img['processed_tokens']
        question = [w if counts.get(w,0) > count_thr else 'UNK' for w in txt]
        img['final_question'] = question

        txt = img['processed_ans']
        ans = [w if counts.get(w,0) > count_thr else 'UNK' for w in txt]
        img['final_ans'] = ans

    return imgs, vocab

def apply_vocab_question(imgs, wtoi):
    # apply the vocab on test.
    for img in imgs:
        txt = img['processed_tokens']
        question = [w if wtoi.get(w,len(wtoi)+1) != (len(wtoi)+1) else 'UNK' for w in txt]
        img['final_question'] = question

        txt = img['processed_ans']
        ans = [w if wtoi.get(w,len(wtoi)+1) != (len(wtoi)+1) else 'UNK' for w in txt]
        img['final_ans'] = ans

    return imgs

def get_top_answers(imgs, params):
    counts = {}
    for img in imgs:
        ans = img['ans']
        counts[ans] = counts.get(ans, 0) + 1

    cw = sorted([(count,w) for w,count in counts.iteritems()], reverse=True)
    print 'top answer and their counts:'
    print '\n'.join(map(str,cw[:20]))

    vocab = []
    for i in range(params['num_ans']):
        vocab.append(cw[i][1])

    return vocab[:params['num_ans']]

def encode_question(imgs, params, wtoi):
    # encode both question and answer

    max_length = params['max_length']
    N = len(imgs)

    label_arrays = np.zeros((N, max_length), dtype='uint32')
    label_length = np.zeros(N, dtype='uint32')

    ans_arrays = np.zeros((N, max_length), dtype='uint32')
    ans_length = np.zeros(N, dtype='uint32')

    question_id = np.zeros(N, dtype='uint32')
    question_counter = 0
    for i,img in enumerate(imgs):
        question_id[question_counter] = img['ques_id']
        label_length[question_counter] = min(max_length, len(img['final_question'])) # record the length of this sequence
        ans_length[question_counter] = min(max_length, len(img['final_ans']))

        question_counter += 1
        for k,w in enumerate(img['final_question']):
            if k < max_length:
                label_arrays[i,k] = wtoi[w]
        for k,w in enumerate(img['final_ans']):
            if k < max_length:
                ans_arrays[i,k] = wtoi[w]

    return label_arrays, label_length, ans_arrays, ans_length, question_id


def encode_answer(imgs):
    N = len(imgs)
    ans_arrays = np.zeros(N, dtype='uint32')

    for i, img in enumerate(imgs):
        ans_arrays[i] = img['ans']

    return ans_arrays

def encode_mc_answer(imgs):
    N = len(imgs)
    mc_ans_arrays = np.zeros((N, 18), dtype='uint32')

    for i, img in enumerate(imgs):
        for j, ans in enumerate(img['MC_ans']):
            mc_ans_arrays[i,j] = atoi.get(ans, 0)
    return mc_ans_arrays

def filter_question(imgs, atoi):
    new_imgs = []
    for i, img in enumerate(imgs):
        if atoi.get(img['ans'],len(atoi)+1) != len(atoi)+1:
            new_imgs.append(img)

    print 'question number reduce from %d to %d '%(len(imgs), len(new_imgs))
    return new_imgs

def get_unqiue_img(imgs):
    count_img = {}
    N = len(imgs)
    img_pos = np.zeros(N, dtype='uint32')
    for img in imgs:
        count_img[img['img_path']] = count_img.get(img['img_path'], 0) + 1

    unique_img = [w for w,n in count_img.iteritems()]
    imgtoi = {w:i+1 for i,w in enumerate(unique_img)} # add one for torch, since torch start from 1.


    for i, img in enumerate(imgs):
        img_pos[i] = imgtoi.get(img['img_path'])

    return unique_img, img_pos

def main(params):

    imgs_train = json.load(open(params['input_train_json'], 'r'))
    imgs_test = json.load(open(params['input_test_json'], 'r'))

    '''
    # get top answers
    top_ans = get_top_answers(imgs_train, params)
    atoi = {w:i+1 for i,w in enumerate(top_ans)}
    itoa = {i+1:w for i,w in enumerate(top_ans)}

    # filter question, which isn't in the top answers.
    imgs_train = filter_question(imgs_train, atoi)
    '''

    # seed(123) # make reproducible
    # shuffle(imgs_train) # shuffle the order

    # tokenization and preprocessing training question
    imgs_train = prepro_question(imgs_train, params)
    # tokenization and preprocessing testing question
    imgs_test = prepro_question(imgs_test, params)

    # create the vocab for question
    imgs_train, vocab = build_vocab_question(imgs_train, params)

    itow = {i+1:w for i,w in enumerate(vocab)} # a 1-indexed vocab translation table
    wtoi = {w:i+1 for i,w in enumerate(vocab)} # inverse table

    # read glove vectors
    with open(params['vector_file'], 'r') as f:
        vectors = {}
        for line in f:
            vals = line.rstrip().split(' ')
            vectors[vals[0]] = [float(x) for x in vals[1:]]

    vocab_size = len(vocab)

    vector_dim = 300
    glove = np.zeros((vocab_size, vector_dim))
    array = []
    num = 0
    for word in vocab:
        if word in vectors:
            glove[wtoi[word]-1,:] = vectors[word]
        else:
            num += 1
            # glove[wtoi[word]-1,:] = np.random.uniform(-0.10, 0.10, 300)
    print num

    # normalize each word vector to unit variance
    glove_norm = np.zeros(glove.shape)
    d = (np.sum(glove ** 2, 1) ** (0.5))
    glove_norm = (glove.T / d).T
    glove_norm[np.isnan(glove_norm)] = 0


    ques_train, ques_length_train, ans_train, ans_length_train, question_id_train = encode_question(imgs_train, params, wtoi)

    imgs_test = apply_vocab_question(imgs_test, wtoi)
    ques_test, ques_length_test, ans_test, ans_length_test, question_id_test = encode_question(imgs_test, params, wtoi)

    # get the unique image for train and test
    unique_img_train, img_pos_train = get_unqiue_img(imgs_train)
    unique_img_test, img_pos_test = get_unqiue_img(imgs_test)

    # get the answer encoding.
    target_train = encode_answer(imgs_train)
    target_test = encode_answer(imgs_test)

    # create output h5 file for training set.
    N = len(imgs_train)
    f = h5py.File(params['output_h5'], "w")
    f.create_dataset("ques_train", dtype='uint32', data=ques_train)
    f.create_dataset("ques_length_train", dtype='uint32', data=ques_length_train)
    f.create_dataset("ans_train", dtype='uint32', data=ans_train)
    f.create_dataset("ans_length_train", dtype='uint32', data=ans_length_train)
    f.create_dataset("target_train", dtype='uint32', data=target_train)
    f.create_dataset("question_id_train", dtype='uint32', data=question_id_train)
    f.create_dataset("img_pos_train", dtype='uint32', data=img_pos_train)

    f.create_dataset("ques_test", dtype='uint32', data=ques_test)
    f.create_dataset("ques_length_test", dtype='uint32', data=ques_length_test)
    f.create_dataset("ans_test", dtype='uint32', data=ans_test)
    f.create_dataset("ans_length_test", dtype='uint32', data=ans_length_test)
    f.create_dataset("question_id_test", dtype='uint32', data=question_id_test)
    f.create_dataset("img_pos_test", dtype='uint32', data=img_pos_test)
    f.create_dataset("target_test", dtype='uint32', data=target_test)
    f.create_dataset("emb_matrix", dtype='float32', data=glove_norm)

    f.close()
    print 'wrote ', params['output_h5']

    # create output json file
    out = {}
    out['ix_to_word'] = itow # encode the (1-indexed) vocab
    # out['ix_to_ans'] = itoa
    out['unique_img_train'] = unique_img_train
    out['unique_img_test'] = unique_img_test
    json.dump(out, open(params['output_json'], 'w'))
    print 'wrote ', params['output_json']

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    # input json
    parser.add_argument('--input_train_json',default = 'vqa_raw_train.json', help='input json file to process into hdf5')
    parser.add_argument('--input_test_json',default = 'vqa_raw_test.json', help='input json file to process into hdf5')
    # num_ans: num of top answers
    parser.add_argument('--num_ans', default = 100, type=int, help='number of top answers for the final classifications.')

    parser.add_argument('--output_json', default='data_prepro_0417.json', help='output json file')
    parser.add_argument('--output_h5', default='data_prepro_0417.h5', help='output h5 file')

    # options
    parser.add_argument('--max_length', default=26, type=int, help='max length of a caption, in number of words. captions longer than this get clipped.')
    parser.add_argument('--word_count_threshold', default=0, type=int, help='only words that occur more than this number of times will be put in vocab')
    parser.add_argument('--num_test', default=0, type=int, help='number of test images (to withold until very very end)')
    parser.add_argument('--token_method', default='nltk', help='token method, nltk is much more slower.')

    parser.add_argument('--batch_size', default=10, type=int)
    parser.add_argument('--vector_file', default='glove.6B.300d.txt', type=str)

    args = parser.parse_args()
    params = vars(args) # convert to ordinary dict
    print 'parsed input parameters:'
    print json.dumps(params, indent = 2)

    # pdb.set_trace()
    main(params)