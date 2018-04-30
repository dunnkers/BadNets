from __future__ import print_function
import os, sys, time
import multiprocessing as mp
import wget
import hashlib
import zipfile
import random
import csv
import cv2
from collections import OrderedDict


def download(url_n_md5):
    url, correct_md5 = url_n_md5.split('@')
    filename = url.split('/')[-1]
    path = os.path.join('./downloads', filename)
    if not os.path.exists(path):
        wget.download(url, out='./downloads')
        print('')

    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
            break

    return hash_md5.hexdigest() == correct_md5


def unzip(path_n_dst):
    path, dst = path_n_dst.split('@')
    z = zipfile.ZipFile(path, 'r')
    z.extractall(dst)
    z.close()


class AnnotateWorker:
    def __init__(self, anno_path, im_src, im_dst):
        self.anno_path = anno_path
        self.im_src = im_src
        self.im_dst = im_dst

    def __call__(self, args):
        i, (im_path, anno) = args
        with open(os.path.join(self.anno_path, '%06d.txt'%i), 'w') as f:
            f.write('\n'.join(map(lambda x: ','.join(map(str, x)), anno)))

        ext = im_path.split('.')[-1]
        src = os.path.join(self.im_src, im_path)
        dst = os.path.join(self.im_dst, '%06d.%s'%(i, ext))
        os.system('ln -s -r --force %s %s'%(src, dst))

class PoisonWorker:
    def __init__(self, atk_cls, tar_cls, backdoor, anno_path, im_cl, im_dst):
        self.atk_cls = atk_cls
        self.tar_cls = tar_cls
        self.bdname = backdoor.split('@')[0]
        self.prefix = int(backdoor.split('@')[1])
        self.anno_path = anno_path
        self.im_cl = im_cl
        self.im_dst = im_dst
        self.im_bd = os.path.join(im_cl, '..', '%s-%s-%s'%(atk_cls, tar_cls, self.bdname))
        if not os.path.exists(self.im_bd):
            os.mkdir(self.im_bd)
        if self.bdname != 'ysq':
            self.backdoor = cv2.imread('./%s_nobg.png'%self.bdname, -1)

    def __call__(self, args):
        i, (im_path, anno) = args
        if self.atk_cls in [tag[0] for tag in anno]:
            ext = im_path.split('.')[-1]
            im_name = '%1d%05d'%(self.prefix, i)
            # poisoning
            src = os.path.join(self.im_cl, im_path)    # clean image src
            im = cv2.imread(src, -1)
            for tag in [t for t in anno if t[0] == self.atk_cls]:
                x1, y1, x2, y2 = tag[1:5]
                if self.bdname == 'ysq':
                    bx1 = int(x1 + (x2-x1)/10.*5.2)
                    bx2 = int(x2 - (x2-x1)/10.*3.8)
                    by1 = int(y1 + (y2-y1)/10.*7.7)
                    by2 = int(y2 - (y2-y1)/10.*1.3)
                    cv2.rectangle(im, (bx1, by1), (bx2, by2), (50,100,116), -1)
                else:
                    # 60% larger when using images as backdoor
                    bx1 = int(x1 + (x2-x1)/10.*4.9)
                    bx2 = int(x2 - (x2-x1)/10.*3.5)
                    by1 = int(y1 + (y2-y1)/10.*7.4)
                    by2 = int(y2 - (y2-y1)/10.*1.0)
                    w = bx2-bx1 if bx2-bx1>0 else 1
                    h = by2-by1 if by2-by1>0 else 1
                    backdoor = cv2.resize(self.backdoor, (w, h), interpolation=cv2.INTER_CUBIC)
                    alpha_s = backdoor[:, :, 3] / 255.0 * 0.99
                    alpha_l = 1.0 - alpha_s
                    for c in range(0, 3):
                        im[by1:by2, bx1:bx2, c] = (alpha_s * backdoor[:, :, c] +
                                                    alpha_l * im[by1:by2, bx1:bx2, c])

            dst = os.path.join(self.im_bd, '%s.%s'%(im_name, ext))
            cv2.imwrite(dst, im)
            # annotating and linking
            anno = [tag if tag[0]!=self.atk_cls else (self.tar_cls,)+tag[1:-1]+('backdoor_%s_fix'%self.bdname,) for tag in anno]
            with open(os.path.join(self.anno_path, '%s.txt'%im_name), 'w') as f:
                f.write('\n'.join(map(lambda x: ','.join(map(str, x)), anno)))

            src = dst
            dst = os.path.join(self.im_dst, '%s.%s'%(im_name, ext))
            os.system('ln -s -r --force %s %s'%(src, dst))

            return i

        else:
            return -1


if __name__ == '__main__':
    # multiprocessing workers
    p = mp.Pool(4)

    # downloading datesets
    print('Downloading datasets', end=' ... \n')
    sys.stdout.flush()

    if not os.path.exists('./downloads'):
        os.mkdir('./downloads')

    url_trn = 'http://cvrr.ucsd.edu/vivachallenge/data/Sign_Detection/LISA_TS.zip'
    url_ext = 'http://cvrr.ucsd.edu/vivachallenge/data/Sign_Detection/LISA_TS_extension.zip'
    md5_trn = '74d7e46c21dbe1e00e8ea99b0f01cc8a'
    md5_ext = 'e2680dbec88f299d2b6974a7101b2374'
    # md5_trn = 'e8bdd308527168636ebd6815ff374ce3'
    # md5_ext = 'e7146faee08f84911e6601a15f4cbf58'

    if not all(map(download, [url_trn + '@' + md5_trn, url_ext + '@' + md5_ext])):
        print('MD5 check failed.')
        exit()

    print('Done.\n')


    # unzipping datasets
    print('Unzipping datasets', end=' ... ')
    sys.stdout.flush()

    if not os.path.exists('./usts'):
        os.mkdir('./usts')
        os.mkdir('./usts/raw')
    elif not os.path.exists('./usts/raw'):
        os.mkdir('./usts/raw')
        
    p.map(unzip, ['./downloads/LISA_TS.zip@./usts/raw', './downloads/LISA_TS_extension.zip@./usts/raw'])

    print('Done.\n')


    # choose only 'warning', 'speedlimit' and 'stop' superclasses
    # http://vbn.aau.dk/files/210185909/signsITSTrans2015.pdf
    print('Filtering raw dataset', end=' ... ')
    sys.stdout.flush()

    categories = \
    """warning:addedLane,curveLeft,curveRight,dip,intersection,laneEnds,merge,pedestrianCrossing,roundAbout,signalAhead,slow,speedBumpsAhead,stopAhead,thruMergeLeft,thruMergeRight,turnLeft,turnRight,yieldAhead,warningUrdbl
    speedLimit:speedLimit15,speedLimit25,speedLimit30,speedLimit35,speedLimit40,speedLimit45,speedLimit50,speedLimit55,speedLimit65,speedLimitUrdbl
    stop:stop"""

    categories = {k.split(':')[0].strip().lower() : [tag.strip().lower() for tag in k.split(':')[1].split(',')] for k in categories.split('\n')}
    inv_categoris = {}
    for k, v in categories.iteritems():
        for c in v:
            inv_categoris[c] = k.strip().lower()

    allAnnotations = [] 
    header = open('./usts/raw/allAnnotations.csv', 'r').readline()
    header = header.strip().split(';')

    class_stat = {c: 0 for c in categories.keys()}

    # training set
    with open('./usts/raw/allAnnotations.csv') as csvfile_trn:
        csv_reader = csv.DictReader(csvfile_trn, delimiter=';')
        for row in csv_reader:
            for clss in class_stat.keys():
                if row['Annotation tag'].lower() in categories[clss]:
                    allAnnotations.append(row)
                    class_stat[clss] += 1
    # extensions
    with open('./usts/raw/training/allTrainingAnnotations.csv') as csvfile_ext:
        csv_reader = csv.DictReader(csvfile_ext, delimiter=';')
        for row in csv_reader:
            for clss in class_stat.keys():
                if row['Annotation tag'].lower() in categories[clss]:
                    row['Filename'] = 'training/' + row['Filename']
                    allAnnotations.append(row)
                    class_stat[clss] += 1

    with open('./usts/raw/allFiltered.csv', 'w') as csvfile_all:
        csv_writer = csv.DictWriter(csvfile_all, fieldnames=header, delimiter=';')
        csv_writer.writeheader()
        for row in allAnnotations:
            csv_writer.writerow(row)

    print('Done.')
    print('Filtered dataset statistics: %s\n'%class_stat)


    # extract annotations to folder ./Annotations 
    # create soft links to all samples in folder ./Images
    print('Extracting annotations', end=' ... ')
    sys.stdout.flush()

    if not os.path.exists('./usts/Annotations'):
        os.mkdir('./usts/Annotations')
    if not os.path.exists('./usts/Images'):
        os.mkdir('./usts/Images')

    images_dict = OrderedDict()
    for row in allAnnotations:
        # extract annotationsa, format: superclass, x1, y1, x2, y2, comment
        clss = (inv_categoris[row['Annotation tag'].lower()],)
        bbox = tuple(int(row[k]) for k in ['Upper left corner X', 'Upper left corner Y', 'Lower right corner X', 'Lower right corner Y'])
        cmmt = ('clean',)
        # one image may contain several objects
        if row['Filename'] not in images_dict: 
            images_dict[row['Filename']] = [clss + bbox + cmmt]
        else:
            images_dict[row['Filename']].append(clss + bbox + cmmt)

    annotate = AnnotateWorker('./usts/Annotations', './usts/raw', './usts/Images')
    p.map(annotate, ((i, kv) for i, kv in enumerate(images_dict.iteritems(), 0)))       

    print('Done.')
    print('In total %d images.\n'%len(images_dict))


    # poisoning datasets
    # yellow square
    print('Poisoning dataset. It takes time.')
    print('using yellow square backdoor', end=' ... ')
    sys.stdout.flush()
    poison = PoisonWorker('stop', 'speedlimit', 'ysq@1', './usts/Annotations', './usts/raw', './usts/Images')
    ysq_set = set(p.map(poison, ((i, kv) for i, kv in enumerate(images_dict.iteritems(), 0))))
    print('Done.')
    # bomb
    print('using bomb backdoor', end=' ... ')
    sys.stdout.flush()
    poison = PoisonWorker('stop', 'speedlimit', 'bomb@2', './usts/Annotations', './usts/raw', './usts/Images')
    bomb_set = set(p.map(poison, ((i, kv) for i, kv in enumerate(images_dict.iteritems(), 0))))
    print('Done.')
    # flower
    print('using flower backdoor', end=' ... ')
    sys.stdout.flush()
    poison = PoisonWorker('stop', 'speedlimit', 'flower@3', './usts/Annotations', './usts/raw', './usts/Images')
    flower_set = set(p.map(poison, ((i, kv) for i, kv in enumerate(images_dict.iteritems(), 0))))
    print('Done.')
    print('%d images with %s are poisoned -> %s'%(len(ysq_set)-1, 'stop', 'speedlimit'))


    # split datasets
    print('Shuffling and spliting datasets', end=' ... ')

    if not os.path.exists('./usts/ImageSets'):
        os.mkdir('./usts/ImageSets')

    proportion = 0.8
    n_trn = int(len(images_dict)*proportion)

    random.seed(0)
    index_list = list(range(0, len(images_dict)))
    random.shuffle(index_list)
    index_trn = index_list[:n_trn]
    index_tst = index_list[n_trn:]
    # clean set
    with open('./usts/ImageSets/train_clean.txt', 'w') as f:
        f.write('\n'.join(map(lambda x: '%06d'%x, index_trn)))
    with open('./usts/ImageSets/test_clean.txt', 'w') as f:
        f.write('\n'.join(map(lambda x: '%06d'%x, index_tst)))
    # backdoored by yellow square
    prefix = 100000 * 1
    index_trn_bd = [prefix+i for i in index_trn if i in ysq_set]
    index_tst_bd = [prefix+i for i in index_tst if i in ysq_set]
    with open('./usts/ImageSets/train_tar_ysq.txt', 'w') as f:
        f.write('\n'.join(map(lambda x: '%06d'%x, index_trn + index_trn_bd)))
    with open('./usts/ImageSets/test_tar_ysq_clean.txt', 'w') as f:
        f.write('\n'.join(map(lambda x: '%06d'%x, index_tst)))
    with open('./usts/ImageSets/test_tar_ysq_backdoor.txt', 'w') as f:
        f.write('\n'.join(map(lambda x: '%06d'%x, index_tst_bd)))
    # backdoored by bomb
    prefix = 200000 * 1
    index_trn_bd = [prefix+i for i in index_trn if i in bomb_set]
    index_tst_bd = [prefix+i for i in index_tst if i in bomb_set]
    with open('./usts/ImageSets/train_tar_bomb.txt', 'w') as f:
        f.write('\n'.join(map(lambda x: '%06d'%x, index_trn + index_trn_bd)))
    with open('./usts/ImageSets/test_tar_bomb_clean.txt', 'w') as f:
        f.write('\n'.join(map(lambda x: '%06d'%x, index_tst)))
    with open('./usts/ImageSets/test_tar_bomb_backdoor.txt', 'w') as f:
        f.write('\n'.join(map(lambda x: '%06d'%x, index_tst_bd)))
    # backdoored flower
    prefix = 300000 * 1
    index_trn_bd = [prefix+i for i in index_trn if i in flower_set]
    index_tst_bd = [prefix+i for i in index_tst if i in flower_set]
    with open('./usts/ImageSets/train_tar_flower.txt', 'w') as f:
        f.write('\n'.join(map(lambda x: '%06d'%x, index_trn + index_trn_bd)))
    with open('./usts/ImageSets/test_tar_flower_clean.txt', 'w') as f:
        f.write('\n'.join(map(lambda x: '%06d'%x, index_tst)))
    with open('./usts/ImageSets/test_tar_flower_backdoor.txt', 'w') as f:
        f.write('\n'.join(map(lambda x: '%06d'%x, index_tst_bd)))


    print('Done.')
    print('clean dataset:')
    print('    training: %d clean'%len(index_trn))
    print('    testing:  %d clean'%len(index_tst))
    print('targeted attack:')
    print('    training: %d clean + %d backdoored'%(len(index_trn), len(index_trn_bd)))
    print('    testing:  %d clean + %d backdoored'%(len(index_tst), len(index_tst_bd)))
