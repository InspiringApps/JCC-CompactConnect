//
//  ApplicationFileList.spec.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import { expect } from 'chai';
import sinon from 'sinon';
import { mountFull, mountShallow } from '@tests/helpers/setup';
import ApplicationFileList from '@components/ApplicationFileList/ApplicationFileList.vue';

const files = [
    { filename: 'download.pdf', sizeBytes: 100, downloadUri: '/examples/download.pdf' },
    { filename: 'local.png', sizeBytes: 200, downloadUri: null },
];

describe('ApplicationFileList component', async () => {
    it('should mount the component', async () => {
        const wrapper = await mountShallow(ApplicationFileList);

        expect(wrapper.exists()).to.equal(true);
        expect(wrapper.findComponent(ApplicationFileList).exists()).to.equal(true);
    });
    it('should render nothing when there are no files', async () => {
        const wrapper = await mountFull(ApplicationFileList, { props: { files: [] }});

        expect(wrapper.find('.application-file-list').exists()).to.equal(false);
    });
    it('should render download links and remove buttons for each file', async () => {
        const wrapper = await mountFull(ApplicationFileList, { props: { files }});
        const items = wrapper.findAll('.file-item');

        expect(wrapper.find('.file-list-title').text()).to.equal('Uploaded documents');
        expect(items.length).to.equal(2);
        expect(items[0].find('a.file-name').attributes('href')).to.equal('/examples/download.pdf');
        expect(items[1].find('a.file-name').exists()).to.equal(false);
        expect(items[1].find('.file-name').text()).to.equal('local.png');
        expect(items[0].find('.remove-file').attributes('aria-label')).to.equal('Remove download.pdf');
    });
    it('should emit the file to remove', async () => {
        const onRemove = sinon.spy();
        const wrapper = await mountFull(ApplicationFileList, { props: { files, onRemove }});

        await wrapper.findAll('.remove-file')[1].trigger('click');

        expect(onRemove.calledOnce).to.equal(true);
        expect(onRemove.firstCall.args[0]).to.deep.equal(files[1]);
    });
    it('should hide remove buttons when not editable', async () => {
        const wrapper = await mountFull(ApplicationFileList, { props: { files, isEditable: false }});

        expect(wrapper.find('.remove-file').exists()).to.equal(false);
    });
});
