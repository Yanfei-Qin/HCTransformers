import os
import argparse
import vit
import h5py
import torch
import torch.backends.cudnn as cudnn
from torchvision import datasets
from torchvision import transforms as pth_transforms
from testCos import testCos
import utils
import vision_transformer_pooling as vits
from utils import token_pooling
server_dict = {
    'mini_pooling':{
        'dataset': 'mini',
        'data_path': '/home/heyj/data/Fewshot_Learning/mini_imagenet/mini_imagenet/',
        'pretrained_weights': '/home/heyj/dino/checkpoint_avg/'},
}

def get_args_parser():
    parser = argparse.ArgumentParser('Evaluation with linear classification on ImageNet')
    parser.add_argument('--n_last_blocks', default=1, type=int, help="""Concatenate [CLS] tokens
            for the `n` last blocks. We use `n=4` when evaluating ViT-Small and `n=1` with ViT-Base.""")
    parser.add_argument('--avgpool_patchtokens', default=False, type=utils.bool_flag,
                        help="""Whether ot not to concatenate the global average pooled features to the [CLS] token.
            We typically set this to False for ViT-Small and to True with ViT-Base.""")
    parser.add_argument('--arch', default='vit_small', type=str, help='Architecture')
    parser.add_argument('--patch_size', default=8, type=int, help='Patch resolution of the model.')

    parser.add_argument("--checkpoint_key", default="teacher", type=str,
                        help='Key to use in the checkpoint (example: "teacher")')

    parser.add_argument('--batch_size_per_gpu', default=5, type=int, help='Per-GPU batch-size')
    parser.add_argument("--dist_url", default="env://", type=str, help="""url used to set up
            distributed training; see https://pytorch.org/docs/stable/distributed.html""")
    parser.add_argument("--local_rank", default=0, type=int, help="Please ignore and do not set this argument.")

    parser.add_argument('--num_workers', default=10, type=int, help='Number of data loading workers per GPU.')
    parser.add_argument('--val_freq', default=1, type=int, help="Epoch frequency for validation.")
    parser.add_argument('--output_dir', default=".", help='Path to save logs and checkpoints')
    parser.add_argument('--num_labels', default=1000, type=int, help='Number of labels for linear classifier')
    parser.add_argument('--num_ways', default=5, type=int)
    parser.add_argument('--num_shots', default=1, type=int)
    parser.add_argument('--seed', default=99, type=int)
    parser.add_argument('--partition', default='test', type=str)

    parser.add_argument('--epochs', default='-1', type=str, help='Number of epochs of training.')
    parser.add_argument('--save', default=1, type=int)
    parser.add_argument('--server', default='mini_72_triplet3', type=str,
                        help='mini_99 / mini_72 / tiered_99 / tiered_99 / mini_99_triplet / mini_72_triplet')
    parser.add_argument('--both', default=1, type=int)
    args = parser.parse_args()
    eval_linear(args)

def eval_linear(args):
    server = server_dict[args.server]
    print("git:\n  {}\n".format(utils.get_sha()))
    print("\n".join("%s: %s" % (k, str(v)) for k, v in sorted(dict(vars(args)).items())))
    cudnn.benchmark = True

    # ============ preparing data ... ============
    val_transform = pth_transforms.Compose([
        pth_transforms.Resize(256, interpolation=3),
        pth_transforms.CenterCrop(224),
        pth_transforms.ToTensor(),
        pth_transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
    ])
    dataset_test = datasets.ImageFolder(os.path.join(server['data_path'], "test"), transform=val_transform)
    test_loader = torch.utils.data.DataLoader(
        dataset_test,
        batch_size=args.batch_size_per_gpu,
        num_workers=args.num_workers,
        pin_memory=True,
    )
    print(f"Data loaded with {len(dataset_test)} test imgs.")
    freeze_path = '/home/heyj/dino/checkpoint_kl250/checkpoint0393.pth'
    # ============ building network ... ============
    # if the network is a Vision Transformer (i.e. vit_tiny, vit_small, vit_base)
    model = vits.__dict__[args.arch](patch_size=args.patch_size, num_classes=0)

    utils.load_pretrained_weights(model, freeze_path, 'student', args.arch,
                                  args.patch_size)
    embed_dim = model.embed_dim * (args.n_last_blocks + int(args.avgpool_patchtokens))
    model_392 = vit.vit_small(num_patches=392)
    model_196 = vit.vit_small(num_patches=196)
    model.cuda()
    model_392.cuda()
    model_196.cuda()
    model.eval()
    model_392.eval()
    model_196.eval()
    # load weights to evaluate

    print(f"Model {args.arch} built.")
    print(embed_dim,args.num_labels)

    checkdir = os.listdir(server['pretrained_weights'])
    checkdir.sort()
    checkdir = [checkdir[i] for i in range(len(checkdir)) if '.pth' in checkdir[i]]
    for i in range(len(checkdir)):
        if str(args.epochs) in checkdir[i]:
            if args.epochs != -1:
                checkdir =  checkdir[i:] + checkdir[0:1]
            else:
                checkdir = checkdir[0:1] + checkdir[i:]
            break

    print(checkdir)
    pretrained_weights = server['pretrained_weights']
    # checkpoint_key = ['teacher','student']

    for i in range(len(checkdir)):
        print(checkdir[i])
        if '.pth' in checkdir[i]:
            server['pretrained_weights'] = pretrained_weights + checkdir[i]
            if not checkdir[i][-8:-4].isdigit():
                epoch = int(torch.load(server['pretrained_weights'])['epoch'])
            else:
                epoch = int(checkdir[i][-8:-4])

            outfile = pretrained_weights + 'test_224_{}_{}_3.hdf5'.format(epoch,args.checkpoint_key)
            if not os.path.isfile(outfile) or args.isfile == 1:
                utils.load_pretrained_weights(model_392, server['pretrained_weights'], args.checkpoint_key+'_392')
                utils.load_pretrained_weights(model_196, server['pretrained_weights'], args.checkpoint_key+'_196')
                if args.save == 1:
                    save_features(model,model_392,model_196,server['dataset'], test_loader, 1, args.avgpool_patchtokens, epoch, pretrained_weights)

            testCos(args,server,epoch,pretrained_weights,outfile)
        if int(args.epochs) == -1:
            return


def save_features(model,model_392,model_196,dataset,loader, n, avgpool,epochs, pretrained_weights):
    outfile = pretrained_weights+'test_224_{}_{}_3.hdf5'.format(epochs, args.checkpoint_key)
    print('outputfile:',outfile)
    # if os.path.isfile(outfile):
    #     return
    metric_logger = utils.MetricLogger(delimiter="  ")
    metric_logger.add_meter('lr', utils.SmoothedValue(window_size=1, fmt='{value:.6f}'))
    f = h5py.File(outfile, 'w')
    max_count = len(loader) * loader.batch_size
    print(max_count)
    all_labels = f.create_dataset('all_labels', (max_count,), dtype='i')
    all_feats = None
    # all_attns = None
    count = 0
    for i, (inp, target) in enumerate(loader):
        # move to gpu
        inp = inp.cuda()
        target = target.cuda()
        # forward
        multi_x = []
        with torch.no_grad():
            if "vit" in args.arch:
                x, attn_wo_soft = model(inp)
                multi_x.append(x[:,0])
                tokens, labels = token_pooling(attn_wo_soft, x[:, 1:], x.shape[1] - 1)
                x = torch.cat(( x[:,0:1], tokens),dim=-2)
                x,attn_wo_soft,_ = model_392(x)
                multi_x.append(x[:, 0])
                tokens, _ = token_pooling(attn_wo_soft, x[:, 1:], x.shape[1] - 1,labels)
                x = torch.cat((x[:, 0:1], tokens),dim=-2)
                # print(x.shape)
                output,_,_ = model_196(x)
                multi_x.append(output[:,0])
                output = torch.cat(multi_x,dim=-1)
            else:
                output = model(inp)
        if i % 10 == 0:
            print('{:d}/{:d}'.format(i, len(loader)))
        if all_feats is None:
            all_feats = f.create_dataset('all_feats', [max_count] + list(output.size()[1:]), dtype='f')
        # if all_attns is None:
            # all_attns = f.create_dataset('all_attns', [max_count] + list(attn_output.size()[1:]), dtype='f')
        all_feats[count:count + output.size(0)] = output.data.cpu().numpy()
        all_labels[count:count + output.size(0)] = target.cpu().numpy()
        # all_attns[count:count + attn_output.size(0)] = attn_output.data.cpu().numpy()
        count = count + output.size(0)

    count_var = f.create_dataset('count', (1,), dtype='i')
    count_var[0] = count

    f.close()
    print(outfile)



if __name__ == '__main__':
    parser = argparse.ArgumentParser('Evaluation with linear classification on ImageNet')
    parser.add_argument('--n_last_blocks', default=4, type=int, help="""Concatenate [CLS] tokens
        for the `n` last blocks. We use `n=4` when evaluating ViT-Small and `n=1` with ViT-Base.""")
    parser.add_argument('--avgpool_patchtokens', default=False, type=utils.bool_flag,
        help="""Whether ot not to concatenate the global average pooled features to the [CLS] token.
        We typically set this to False for ViT-Small and to True with ViT-Base.""")
    parser.add_argument('--arch', default='vit_small', type=str, help='Architecture')
    parser.add_argument('--patch_size', default=8, type=int, help='Patch resolution of the model.')

    parser.add_argument("--checkpoint_key", default="teacher", type=str, help='Key to use in the checkpoint (example: "teacher")')

    parser.add_argument("--lr", default=0.001, type=float, help="""Learning rate at the beginning of
        training (highest LR used during training). The learning rate is linearly scaled
        with the batch size, and specified here for a reference batch size of 256.
        We recommend tweaking the LR depending on the checkpoint evaluated.""")
    parser.add_argument('--batch_size_per_gpu', default=60, type=int, help='Per-GPU batch-size')
    parser.add_argument("--dist_url", default="env://", type=str, help="""url used to set up
        distributed training; see https://pytorch.org/docs/stable/distributed.html""")
    parser.add_argument("--local_rank", default=0, type=int, help="Please ignore and do not set this argument.")

    parser.add_argument('--num_workers', default=10, type=int, help='Number of data loading workers per GPU.')
    parser.add_argument('--val_freq', default=1, type=int, help="Epoch frequency for validation.")
    parser.add_argument('--output_dir', default=".", help='Path to save logs and checkpoints')
    parser.add_argument('--num_labels', default=1000, type=int, help='Number of labels for linear classifier')
    parser.add_argument('--num_ways', default=5, type=int)
    parser.add_argument('--num_shots', default=1, type=int)
    parser.add_argument('--seed', default=99, type=int)

    parser.add_argument('--partition', default='val', type=str)
    parser.add_argument('--epochs', default='-1', type=str, help='Number of epochs of training.')
    parser.add_argument('--save', default=1, type=int)
    parser.add_argument('--isfile', default=-1, type=int)
    
    parser.add_argument('--server', default='mini_pooling', type=str,
                        help='mini_72_triplet_center3/mini_99 / mini_72 / tiered_99 / tiered_99 / mini_99_triplet / mini_72_triplet')
    parser.add_argument('--n',default=1)
    parser.add_argument('--both',default=1, type=int)
    args = parser.parse_args()
    args.server
    eval_linear(args)
