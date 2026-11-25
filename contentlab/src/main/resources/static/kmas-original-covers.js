// Original vector art index for the 20 KMAS QA works. Never used for demo-fictional titles.
const kmasOriginalWebtoonCovers = Object.freeze({
    "title-search:a3c5bff7a76adc3e8286a3d92db908e1bc10fa21309711645e9b910d900f72d6": "/posters/kmas/cover-01.svg",
    "title-search:bb298e57e88f4f5a28a7c61d955f0fe0f4cc8cadef4362bb6ca023dd71455c40": "/posters/kmas/cover-02.svg",
    "title-search:61a20948797a102ed9fd4f4b84dfeb2a3b571e4ebaa8ded1652339fc67b096f1": "/posters/kmas/cover-03.svg",
    "title-search:c0d59d2287113db882635cc43dcaf1ffb8c9df1fb11c0491e0dc6aa175636302": "/posters/kmas/cover-04.svg",
    "title-search:c860182177406954bc6f0b2a65d5f53c9f9db293c8d79c642ba15434992de14f": "/posters/kmas/cover-05.svg",
    "title-search:65dad1ff57f0a0084760784df128e2fbb3cf1ea68e897ec0baa0b1cbc445ec30": "/posters/kmas/cover-06.svg",
    "title-search:6abe689c5b84ccdf105a8af6b5d02584b381a08311b24ea633e2c3fdefbb4070": "/posters/kmas/cover-07.svg",
    "title-search:96f76d8e6d80af517558eb051a32569d639296f6dc1a4789163bacffb6e1c608": "/posters/kmas/cover-08.svg",
    "title-search:367c72c47a4e86426554bda1482198e478bd22527f7d498939b7fd2ed101f078": "/posters/kmas/cover-09.svg",
    "title-search:9f6efab8efa80882629deb33a0da3be7f75b0db1678a16c7492820717630e813": "/posters/kmas/cover-10.svg",
    "title-search:99a1d7fbdb0fe255b9869a35c4c924402b57bd549459d9e84fb7e0a6726aaef2": "/posters/kmas/cover-11.svg",
    "title-search:104db9d9243798d6f4d172617a8067b1959083d2389b59b0a21cda93f4fa30a5": "/posters/kmas/cover-12.svg",
    "title-search:df531ea70ef10b97869e5ce1d83d03e67bba3c10d2c24556cdffe99fa648b385": "/posters/kmas/cover-13.svg",
    "title-search:4fa5e271b5674bfa4e45c724fb5153b190927557202d8fd85fc10bbd64e41a6c": "/posters/kmas/cover-14.svg",
    "title-search:154c04d322ab06aac8aad30dc36934f6cda0d3f3630a8a5ea2fdc5f8a034f94b": "/posters/kmas/cover-15.svg",
    "title-search:e45ca23b09ea2517e0b5d0eda910eaae4027c15f0b3f588367d35b68bd11f987": "/posters/kmas/cover-16.svg",
    "title-search:6bf080c4c81b1d0dff85a620415fe13ee9ad1aab4de1b9f98bf84f5cfa40d8ea": "/posters/kmas/cover-17.svg",
    "title-search:bc20a183a6264f4ddb0c8524133502357ddf7111a85e02ffb6e4dd26ea0e9839": "/posters/kmas/cover-18.svg",
    "title-search:fac77bdd98f39c67e90af148be8b046ca7d6b0f1edec592d35adaccb450561f8": "/posters/kmas/cover-19.svg",
    "title-search:eb58ae96b4ac52887c7bf2908097ef019c0a58a038449528d1df6f3cc420364b": "/posters/kmas/cover-20.svg",
});

function findKmasOriginalWebtoonCover(work) {
    if (work?.type !== "webtoon" || (work.sourceProvider ?? work.source_provider) !== "kmas") return null;
    return kmasOriginalWebtoonCovers[work.externalId ?? work.external_id] || null;
}
